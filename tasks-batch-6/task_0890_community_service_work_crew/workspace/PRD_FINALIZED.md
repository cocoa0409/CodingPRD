# Community-Service & Work-Crew Program API — Product Requirements Document

## 1. Introduction

When a court sentences an offender to community service, the resulting obligation is deceptively hard to administer. A single order — say, "120 hours by the end of the year" — must be routed to a host agency willing to take the participant, backed by valid liability insurance, staffed by a supervisor who signs off on attendance, and reconciled hour-by-hour against the number the judge actually wrote down. Along the way the participant may fall behind and be reported back to court, may buy out a portion of the balance through a sliding-scale conversion fee, or may finish early and earn a completion certificate that the clerk files with the docket. Every one of those events touches the same running ledger of hours, and the court expects that ledger to be exact.

This document specifies a backend REST API for running such a program end to end. It manages the reference data (participants, host sites, insurance policies, supervisors), the court-facing lifecycle (referrals, compliance actions, reinstatement, termination), the field operations (placements, liability waivers, scheduled work sessions, check-in/check-out, and hour verification), and the fiscal side (fee conversions that discharge outstanding hours for money). The domain is compliance-heavy: segregation of duties between the office that requests a fee conversion and the office that approves it, optimistic concurrency so that a stale view of a referral cannot silently overwrite hours another actor already credited, and a conserved partition invariant guaranteeing that ordered hours always equal the sum of completed, converted, and outstanding hours.

Because deadlines, coverage windows, and rest buffers are all evaluated against time, the system runs on a **logical clock** rather than wall-clock time. The clock starts at a fixed instant and only moves when a test-driving endpoint advances it, so that every temporal comparison in the specification is reproducible.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is missing, or if `X-User-Role` is not one of the four roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role (or, where applicable, the specific identity) is not permitted to perform the operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles are spelled exactly as follows:

- **`CourtClerk`** — court staff. Issues referrals, files compliance actions, and decides reinstatement and termination. When `X-User-Role` is `CourtClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it (for example, as `filed_by_user_id` on a `ComplianceAction`) but never compares it to any entity's `id`.
- **`ProgramCoordinator`** — the program office. Manages sites, insurance, supervisors, placements, work-session scheduling, and the approval side of fee conversions. When `X-User-Role` is `ProgramCoordinator`, `X-User-ID` is likewise an opaque operator identifier; the server may record it (for example, as `approved_by_user_id` on a `FeeConversion`) but does not compare it to any entity's `id`.
- **`SiteSupervisor`** — the on-site supervisor who runs check-in/out and verifies hours. When `X-User-Role` is `SiteSupervisor`, `X-User-ID` is the `id` of the acting `Supervisor`; ownership checks on any work session compare the `supervisor_id` of the session's placement to `X-User-ID`. A supervisor who is not the placement's assigned supervisor is rejected with `ERR_UNAUTHORIZED`.
- **`Participant`** — the person serving the hours. Signs waivers and requests and pays fee conversions on their own referrals. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant`; ownership checks compare the `participant_id` of the referral behind a placement or conversion to `X-User-ID`.

Read (`GET`) operations are available to all four roles across the collections each role is entitled to see. Write operations are gated per §4 and reinforced throughout §3.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset` defaults to 0 and must be at least 0. A `limit` outside 1–100 or a negative `offset` is rejected with `ERR_PAGINATION_INVALID` (HTTP 400). List results are ordered by `created_at` ascending. The `meta` block of every list response reports `limit`, `offset`, `total_count` (the total number of matching records ignoring the window), and `has_more` (true when records remain beyond the current window).

### 2.4. Common Resource Properties, Identifiers, and the Logical Clock

Every persisted resource carries a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format) and an integer `version` that starts at 1 and increments by 1 on every mutation. Two resources are exceptions: a `ComplianceAction` and a `Certificate` are immutable, append-only records that carry only `id` and `created_at` — they have no `updated_at` and no `version`, because once written they are never modified.

The **logical clock** governs every temporal evaluation: referral deadlines, insurance effective and expiry windows, waiver signing instants, session check-in/out defaults, and the participant rest buffer. Its startup default is `2026-05-01T00:00:00Z`; before any clock-setting call the clock reads exactly this instant and never falls back to real wall-clock time. An administrative test-driving capability sets the clock to a supplied `to_iso8601` instant, and all subsequent time comparisons use that value. Whenever a system field is described as "the current clock" — for example `waiver_signed_at`, `check_in_at` when no explicit value is given, or a certificate's `issued_at` — it is this logical clock that is read.

### 2.5. Optimistic Concurrency on Referrals

Creating a fee conversion is guarded by optimistic concurrency against the target referral. The create request must carry `expected_referral_version`, holding the `version` of the referral the client last observed. If that value does not match the referral's current `version` at the moment the create is processed, the request is rejected with `ERR_STALE_REFERRAL_VERSION` (HTTP 412). This matters because a conversion's quoted fee is computed over the referral's outstanding hours, and several unrelated operations — a work-session verification crediting hours, or an earlier conversion request that superseded a prior one — advance the referral's `version`. A mismatch means the client is working from a stale view of the outstanding balance, so the create is refused rather than allowed to price against numbers that have already moved. No other endpoint takes a version field; concurrency control applies only to fee-conversion creation.

### 2.6. Precision, Rounding, and the Quarter-Hour Grid

Service hours are always tracked on a **quarter-hour grid** (increments of 0.25 hours). Any hours value supplied as input — `hours_ordered` on a referral, `hours_to_convert` on a conversion, an `attested_hours` override on verification — must be strictly positive and an exact multiple of 0.25; otherwise the request is rejected with `ERR_VALIDATION` (HTTP 400).

Two derived hour values are computed by rounding to this grid. Rounding to the grid means dividing the raw value by 0.25, rounding that quotient half-up to the nearest whole number, and multiplying back by 0.25 — equivalently, snapping to the nearest 0.25 boundary with ties going upward. Grid-snapped hour figures are expressed to two decimal places.

Monetary amounts are integer cents. Fee arithmetic rounds half-up to a whole cent before any clamping is applied, as detailed in §3.6.

### 2.7. The Hours Partition and Ledger Conservation

Each referral maintains four hour figures that together form a conserved partition. `hours_ordered` is the immutable court order. `hours_completed` is the sum of verified hours from work. `hours_converted` is the sum of hours discharged by paid fee conversions. `hours_outstanding` is what remains, computed as `hours_ordered` minus `hours_completed` minus `hours_converted`, floored at zero (never negative). The governing invariant, which must hold at all times, is that `hours_ordered` equals `hours_completed` plus `hours_converted` plus `hours_outstanding`. Every operation that changes completed or converted hours must recompute `hours_outstanding` so the partition stays balanced. The money counterpart, `fees_settled_cents`, is the net settled conversion money: the sum of settlement fees for conversions currently in `PAID` status minus the sum for those that have been `REVERSED`.

### 2.8. Cascading State Propagation and Nested Retrieval

Many state changes cascade to dependent resources, and these cascades are part of the contract, not an optimization. When a referral moves out of `ACTIVE` its placements follow, and when a placement is suspended or terminated its still-`SCHEDULED` sessions are cancelled. The precise cascades are specified alongside each workflow in §3. Any mutation — direct or cascaded — refreshes the affected resource's `updated_at` and bumps its `version` (for resources that carry those fields).

Every endpoint whose path nests identifiers validates them left to right: a parent that does not exist yields `ERR_NOT_FOUND` (HTTP 404) before any child is considered, and likewise any body-referenced resource that does not exist yields `ERR_NOT_FOUND`. Existence is checked before state, state before finer business rules.

### 2.9. Validation Ordering

When several checks could reject one request, they are evaluated in a fixed priority order so the returned `error_id` is deterministic. The order is: (1) authentication — headers present and role known, else `ERR_UNAUTHENTICATED`; (2) authorization — role permitted and entity-backed ownership satisfied, else `ERR_UNAUTHORIZED`; (3) existence of all path- and body-referenced resources, left to right, else `ERR_NOT_FOUND`; (4) business referential integrity, such as a placement's supervisor belonging to the placement's site, else `ERR_SUPERVISOR_SITE_MISMATCH`; (5) body/field validation — enum membership, positivity, the quarter-hour grid, `scheduled_end` after `scheduled_start`, `check_out_at` after `check_in_at`, and fee-amount matching — else `ERR_VALIDATION`; (6) the fee-conversion stale-version check, else `ERR_STALE_REFERRAL_VERSION`; (7) the generic state check that a resource admits the requested transition, else `ERR_INVALID_STATE`; and then the specific state and business guards (referral-not-active, placement-not-active, waiver, site-accepting, insurance, self-approval, session buffers, capacity, hours limits) described in §3. In short: authentication, then authorization, then existence, then referential integrity, then field validation, then concurrency, then state, then the domain-specific guards.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Host Site: Sites, Insurance, and Supervisors

A `ProgramCoordinator` builds the intake infrastructure before any participant can serve hours. Registering a host site captures its `name`, its `agency_type` (one of `NONPROFIT`, `GOVERNMENT`, `FAITH_BASED`, or `OTHER`), its `address`, and its `capacity_slots` — the maximum number of participants who may be on site at any single instant, which must be at least 1. A newly created site opens in `PROSPECTIVE` status.

A site cannot accept anyone until it is insured. A liability policy is filed against a site by supplying the covered `site_id`, the `carrier` name, the `coverage_amount_cents` (at least 0), the `effective_date`, and the `expiry_date`; the policy opens in `PENDING`. The coordinator then either verifies it, moving it from `PENDING` to `VERIFIED`, or rejects it, moving it from `PENDING` to `REJECTED` (an optional `reason` may accompany the rejection). Both `VERIFIED` and `REJECTED` are terminal. Verification is only allowed while the policy has not yet expired: if the policy's `expiry_date` is at or before the current clock, verification is refused with `ERR_INSURANCE_INVALID` (HTTP 409). A policy is considered valid coverage only while `VERIFIED` and while the clock has not yet reached its `expiry_date`.

Activating a site moves it from `PROSPECTIVE` (or from a later `PAUSED`) to `ACCEPTING`, but only if the site has at least one `VERIFIED` insurance policy whose `expiry_date` is still after the current clock; without such coverage the activation is refused with `ERR_INSURANCE_INVALID`. Pausing a site moves it from `ACCEPTING` to `PAUSED`; while paused, new placements to the site are blocked, but placements and sessions already in flight are unaffected. A site never reaches a terminal state — it can cycle between `ACCEPTING` and `PAUSED` as coverage and staffing change.

Supervisors are registered against a site by supplying the `site_id` and the supervisor's `full_name`, together with an optional `max_concurrent_participants` advisory ceiling that defaults to 5 when omitted and must be at least 1.

### 3.2. The Court Order: Creating and Reporting a Referral

Only a `CourtClerk` may open a referral, which represents the court order itself. Creation captures the `participant_id` of the person ordered to serve, the originating `court_case_number`, the `offense_class` (one of `INFRACTION`, `MISDEMEANOR`, or `FELONY`), the `hours_ordered` (strictly positive and on the quarter-hour grid), the court-ordered `deadline_date`, and an optional `indigency_status` (one of `NONE`, `PARTIAL`, or `FULL`, defaulting to `NONE`) that later drives the sliding-scale conversion rate. A participant is registered separately with a `full_name`, `date_of_birth`, `contact_email`, and an optional `risk_level` (one of `LOW`, `MEDIUM`, or `HIGH`, defaulting to `LOW`).

A new referral opens in `ACTIVE` with its ledger initialized: `hours_completed`, `hours_converted`, and `fees_settled_cents` at 0, `hours_outstanding` equal to `hours_ordered`, `certificate_id` null, and `version` at 1. The referral's terminal states are `COMPLETED`, `CONVERTED`, and `TERMINATED`.

Reporting is served two ways. Fetching a referral returns its full record. A dedicated summary view returns a computed breakdown for a single referral: its `referral_id`, `hours_ordered`, `hours_completed`, `hours_converted`, `hours_outstanding`, `fees_settled_cents`, `status`, and `certificate_id`. Both are readable by every role.

### 3.3. Placing a Participant and the Liability Waiver

With a site accepting and a supervisor on staff, a `ProgramCoordinator` proposes a placement, tying a referral to a host site under a named supervisor. The proposal supplies the `referral_id`, the `site_id`, and the `supervisor_id`. Referential integrity is enforced at creation: the named supervisor must belong to the named site, otherwise the request is rejected with `ERR_SUPERVISOR_SITE_MISMATCH` (HTTP 422). A new placement opens in `PROPOSED` with `waiver_signed` false, `waiver_signed_at` null, and `waiver_signature_name` null.

Before a placement can go active, the participant must sign the liability waiver. Signing is reserved to the `Participant` who owns the placement's referral, and it records the typed `signature_name` as `waiver_signature_name`, sets `waiver_signed` to true, and stamps `waiver_signed_at` with the current clock.

Activating a placement advances it from `PROPOSED` to `ACTIVE`, and is the moment where four preconditions converge. The waiver must be signed, or the request is refused with `ERR_WAIVER_REQUIRED` (HTTP 409). The host site must currently be `ACCEPTING`, or `ERR_SITE_NOT_ACCEPTING` (HTTP 409). The site must carry a `VERIFIED`, non-expired insurance policy, or `ERR_INSURANCE_INVALID` (HTTP 409). And the referral must still be `ACTIVE`, or `ERR_REFERRAL_NOT_ACTIVE` (HTTP 409). A placement may be terminated by the coordinator from `PROPOSED`, `ACTIVE`, or `SUSPENDED`; termination from `ACTIVE` (like other paths that halt an active placement) additionally cancels the placement's still-`SCHEDULED` sessions. Placement terminal states are `COMPLETED` and `TERMINATED`.

### 3.4. Scheduling Work Sessions: Capacity and Rest Buffers

A work session is scheduled under a placement by either a `SiteSupervisor` or a `ProgramCoordinator`. Scheduling does not check the placement's status — a session may be scheduled under a placement in any status (for example, a `PROPOSED` placement that has not yet been activated), and the only scheduling guards are the three described below. The scheduler supplies the `placement_id`, the planned `scheduled_start` and `scheduled_end` (the end must be strictly after the start, else `ERR_VALIDATION`), and an optional `session_category` — one of `STANDARD`, `WEEKEND_CREW`, or `ALTERNATIVE`, defaulting to `STANDARD` — which distinguishes ordinary service from weekend-crew and alternative arrangements. At creation the session denormalizes the `participant_id` and `site_id` from its placement (so later overlap and capacity checks need not re-traverse), opens with `attendance_status` `SCHEDULED` and `verification_status` `PENDING`, and leaves `check_in_at`, `check_out_at`, `claimed_hours`, and `verified_hours` unset.

Three scheduling guards protect the calendar, evaluated after field validation:

- **Participant rest buffer.** Consider the candidate interval against every other session belonging to the same participant whose `attendance_status` is `SCHEDULED`, `CHECKED_IN`, or `COMPLETED`. Compute the gap in minutes between the candidate and each such session, treating any overlap as a gap of zero. If the smallest such gap is under 60 minutes the schedule is refused with `ERR_SESSION_OVERLAP` (HTTP 409). A gap of exactly 60 minutes is allowed; 59 is rejected. The participant must therefore have at least a one-hour rest between the end of one session and the start of the next.
- **Supervisor double-booking.** The placement's assigned supervisor must not already staff a session whose interval overlaps the candidate's. Intervals are treated as half-open, so two sessions that merely touch end-to-start are considered adjacent and allowed; genuine overlap is refused with `ERR_SUPERVISOR_DOUBLE_BOOKED` (HTTP 409).
- **Site capacity.** Count the other sessions on the same site whose `attendance_status` is `SCHEDULED` or `CHECKED_IN` and whose half-open interval shares any instant with the candidate. If adding this session would make the concurrent count exceed the site's `capacity_slots`, the schedule is refused with `ERR_SITE_CAPACITY_EXCEEDED` (HTTP 409). Capacity is a half-open interval count, so a session that starts exactly when another ends does not count as concurrent.

### 3.5. Attendance and Hour Verification

The supervisor who owns a placement runs the session lifecycle, and only that supervisor: check-in, check-out, and verify all require the acting `SiteSupervisor`'s `X-User-ID` to equal the placement's `supervisor_id`, else `ERR_UNAUTHORIZED`.

Checking in advances a session from `SCHEDULED` to `CHECKED_IN`, but only while the placement is `ACTIVE`; if the placement is not active the check-in is refused with `ERR_PLACEMENT_NOT_ACTIVE` (HTTP 409). Check-in sets `check_in_at` to a supplied value or, if none is given, to the current clock.

Checking out advances the session from `CHECKED_IN` to `COMPLETED`. The supplied (or defaulted) `check_out_at` must be strictly after `check_in_at`; otherwise the check-out is refused with `ERR_CHECKOUT_BEFORE_CHECKIN` (HTTP 422). At check-out the system computes `claimed_hours` — the self-reported duration — by taking the elapsed time from `check_in_at` to `check_out_at` in seconds, dividing by 3600 to get raw hours, and snapping that to the quarter-hour grid (nearest 0.25, ties upward).

Verification is a separate axis that evolves independently of attendance; a session stays in attendance `COMPLETED` throughout. The supervisor verifies with an `outcome` of `VERIFIED`, `DISPUTED`, or `REJECTED`, and may include an `attested_hours` override:

- **`VERIFIED`** credits the referral. It is allowed only when attendance is `COMPLETED` (else `ERR_INVALID_STATE`, HTTP 409) and `verification_status` is currently `PENDING` or `DISPUTED` (else `ERR_INVALID_STATE`). If the supervisor supplies `attested_hours` (for instance to deduct an unpaid break), that value must be on the quarter-hour grid and must not exceed `claimed_hours` — an over-attestation is refused with `ERR_VERIFIED_HOURS_EXCEED_CLAIMED` (HTTP 422). The credited `verified_hours` is the grid-snapped `attested_hours` when supplied, and otherwise equals `claimed_hours` outright; the two approaches deliberately diverge for the same session, since a supervisor attestation lands strictly below the participant's clock-derived claim. On a `VERIFIED` outcome, `verification_status` becomes `VERIFIED`, `verified_hours` is added to the referral's `hours_completed`, and `hours_outstanding` is recomputed.
- **`DISPUTED`** is allowed only from `verification_status` `PENDING` (else `ERR_INVALID_STATE`). It sets `verification_status` to `DISPUTED` and credits no hours.
- **`REJECTED`** is allowed from `verification_status` `PENDING` or `DISPUTED` (else `ERR_INVALID_STATE`). It sets `verification_status` to `REJECTED` and credits no hours.

The referral's `hours_completed` is, at all times, the sum of `verified_hours` across that referral's sessions that are `VERIFIED` and not `VOIDED`. Each session's `verified_hours` is already snapped to the quarter-hour grid; the sum is taken over those already-rounded per-session values and is not re-rounded. The order is fixed: round each session, then sum — never sum raw durations and round the total.

If, after crediting, the referral's `hours_completed` is at least its `hours_ordered` (the boundary is inclusive — exact equality completes) and `hours_outstanding` has reached 0, the referral automatically completes, as described in §3.8.

A completed session may later be voided by a `ProgramCoordinator` or a `SiteSupervisor`, moving `attendance_status` to `VOIDED` (an optional `reason` may be recorded). If the session had been `VERIFIED`, voiding reverses its credit by subtracting its `verified_hours` from the referral's `hours_completed` and recomputing `hours_outstanding`; a void may never drive `hours_completed` below 0. Because the referral's `hours_completed` is defined as the sum over `VERIFIED`, non-`VOIDED` sessions, the voided session simply drops out of that sum. A reversal that drops `hours_completed` back below `hours_ordered` may reopen a referral that had completed by work; attempting to void in a way that conflicts with a referral already terminal by another path is refused with `ERR_INVALID_STATE`.

### 3.6. Buying Out Hours: Fee Conversions

A participant who cannot finish all ordered hours may discharge some of them for money. A conversion is requested by the owning `Participant` (or by a `ProgramCoordinator`) against a referral, supplying the `referral_id`, the `hours_to_convert` (strictly positive, on the quarter-hour grid), and `expected_referral_version` for the concurrency guard of §2.5. The requested hours may not exceed the referral's current `hours_outstanding`, else `ERR_HOURS_EXCEED_OUTSTANDING` (HTTP 422). A new request supersedes any prior conversion still in `REQUESTED` status for the same referral by moving that prior one to `DENIED`, and it advances the referral's `version` by 1 — which is exactly why the next requester needs a fresh `expected_referral_version`. On creation the conversion opens in `REQUESTED`, snapshots the referral's `indigency_status` into `indigency_status_snapshot` (pinning the rate tier for the life of the conversion), records the creating `X-User-ID` as `requested_by_user_id`, and computes a provisional `quoted_fee_cents` over the requested `hours_to_convert`.

The **conversion fee** is a sliding-scale, tiered-then-clamped amount in cents. The per-hour rate is a base of 1500 cents (fifteen dollars per hour) multiplied by an indigency factor keyed to the snapshot tier: 1.0 for `NONE` (fifteen dollars an hour), 0.5 for `PARTIAL` (seven dollars fifty an hour), and 0.25 for `FULL` (three dollars seventy-five an hour). The raw fee is the number of hours multiplied by that per-hour rate, rounded half-up to a whole cent. The raw fee is then clamped into a band: first raised to a floor of 2500 cents ($25) if below it, then capped at a ceiling of 200000 cents ($2000) if above it. The provisional quote uses the as-requested `hours_to_convert`; the final settlement, computed at payment time, uses the actually-settled hours and is therefore no larger than the quote whenever outstanding hours fell between request and payment.

Approval enforces four-eyes segregation of duties. A `ProgramCoordinator` approves, moving the conversion from `REQUESTED` to `APPROVED`, but the approver's `X-User-ID` must differ from the `requested_by_user_id`; a self-approval is refused with `ERR_SELF_APPROVAL` (HTTP 403). The referral must also still be `ACTIVE`, else `ERR_REFERRAL_NOT_ACTIVE`. Approval records the approver as `approved_by_user_id`. Alternatively the coordinator may deny a `REQUESTED` conversion, moving it to the terminal `DENIED` (an optional `reason` may be recorded).

Payment settles an `APPROVED` conversion and is performed by the owning `Participant` or a `ProgramCoordinator`. The referral must have outstanding hours to settle: if `hours_outstanding` is 0 the payment is refused with `ERR_NO_REMAINING_HOURS` (HTTP 409). The payer supplies `amount_cents`, which must equal the settlement fee computed at pay time, or the payment is refused with `ERR_VALIDATION`. At settlement the system computes `settled_hours` as the smaller of `hours_to_convert` and the referral's current `hours_outstanding`, then computes `settlement_fee_cents` by the same sliding-scale-then-clamp formula over `settled_hours` at the pinned snapshot tier. The conversion moves to `PAID`, `settled_hours` is added to the referral's `hours_converted`, `settlement_fee_cents` is added to `fees_settled_cents`, and `hours_outstanding` is recomputed. If that drives `hours_outstanding` to 0, the referral automatically converts, as described in §3.8.

Reversal is the compensating action, performed by a `ProgramCoordinator` on an `APPROVED` or `PAID` conversion, moving it to the terminal `REVERSED` (an optional `reason` may be recorded). Reversing a conversion that had only been approved simply closes it. Reversing a `PAID` conversion unwinds the ledger: it subtracts the conversion's `settled_hours` from the referral's `hours_converted`, subtracts its `settlement_fee_cents` from `fees_settled_cents`, and recomputes `hours_outstanding`. If the referral had reached `CONVERTED` solely because of this conversion, reversing it restores the referral to `ACTIVE`, so that both the hours partition and the money total return to their pre-conversion values.

### 3.7. Non-Compliance, Reinstatement, and Termination

When a participant falls behind, a `CourtClerk` files a compliance action against the referral, an append-only court record. Filing supplies the `referral_id`, the `action_type` (either `WARNING` or `REPORT_BACK`), and a narrative `reason`; the server records the filing clerk as `filed_by_user_id` and pins `resulting_referral_status` to the referral's status immediately after the action. A `WARNING` is advisory: it leaves the referral `ACTIVE`, so `resulting_referral_status` is `ACTIVE`. A `REPORT_BACK` reports the participant back to court and drives the referral from `ACTIVE` to `NON_COMPLIANT`, so `resulting_referral_status` is `NON_COMPLIANT`; this cascades every `ACTIVE` placement for the referral to `SUSPENDED`, and each such suspension in turn cancels that placement's still-`SCHEDULED` sessions (moving them to `CANCELLED`).

A `NON_COMPLIANT` referral can be brought back. Reinstatement, filed by a `CourtClerk`, returns the referral from `NON_COMPLIANT` to `ACTIVE` and cascades every `SUSPENDED` placement for that referral back to `ACTIVE`. This forms the reinstatement loop: a referral may pass `ACTIVE → NON_COMPLIANT → ACTIVE` more than once. Alternatively the clerk may terminate a `NON_COMPLIANT` referral, moving it to the terminal `TERMINATED` (an optional `reason` may be recorded); termination cascades every non-terminal placement — those in `PROPOSED`, `ACTIVE`, or `SUSPENDED` — to `TERMINATED`.

### 3.8. Completion, Certificates, and the Reporting Ledger

A referral finishes one of two ways, and either way the system acts automatically. When a verification credit brings `hours_completed` to at least `hours_ordered` and `hours_outstanding` to 0, the referral moves from `ACTIVE` to `COMPLETED`. When instead a paid fee conversion drives `hours_outstanding` to 0 while `hours_completed` is still below `hours_ordered` — the balance discharged by fee rather than by work — the referral moves from `ACTIVE` to `CONVERTED`. In both cases the system auto-issues a completion certificate and cascades every `ACTIVE` placement for the referral to `COMPLETED`.

The certificate is an immutable record. At issuance the system mints a human-readable `certificate_number`, pins `total_hours_credited` to the referral's `hours_completed` plus `hours_converted` at that instant, stamps `issued_at` with the current clock, records the `referral_id`, and writes the new certificate's `id` back onto the referral as `certificate_id`. Certificates are read-only thereafter and can be fetched or listed by any role.

## 4. Endpoint Definitions

All endpoints share the standard envelope of §2.2. Resource creation returns HTTP 201; state transitions, mutations, reads, and the clock capability return HTTP 200. Request and response payloads are reconstructed from the workflow narratives in §3; the table below lists only method, path, purpose, and the roles authorized to call each endpoint.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the server logical clock | CourtClerk, ProgramCoordinator |
| POST | `/participants` | Register a participant | CourtClerk, ProgramCoordinator |
| GET | `/participants/{id}` | Fetch a participant | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| GET | `/participants` | List participants | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| POST | `/sites` | Create a host site/agency | ProgramCoordinator |
| GET | `/sites/{id}` | Fetch a site | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| GET | `/sites` | List sites | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| POST | `/sites/{id}/activate` | Activate a site to ACCEPTING | ProgramCoordinator |
| POST | `/sites/{id}/pause` | Pause a site (ACCEPTING → PAUSED) | ProgramCoordinator |
| POST | `/insurance-policies` | File a liability policy for a site | ProgramCoordinator |
| GET | `/insurance-policies/{id}` | Fetch an insurance policy | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| GET | `/insurance-policies` | List insurance policies | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| POST | `/insurance-policies/{id}/verify` | Verify a policy (PENDING → VERIFIED) | ProgramCoordinator |
| POST | `/insurance-policies/{id}/reject` | Reject a policy (PENDING → REJECTED) | ProgramCoordinator |
| POST | `/supervisors` | Register a site supervisor | ProgramCoordinator |
| GET | `/supervisors/{id}` | Fetch a supervisor | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| GET | `/supervisors` | List supervisors | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| POST | `/referrals` | Create a court referral | CourtClerk |
| GET | `/referrals/{id}` | Fetch a referral | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| GET | `/referrals` | List referrals | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| GET | `/referrals/{id}/summary` | Computed hours/fee breakdown | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| POST | `/referrals/{id}/reinstate` | Reinstate a NON_COMPLIANT referral | CourtClerk |
| POST | `/referrals/{id}/terminate` | Terminate a NON_COMPLIANT referral | CourtClerk |
| POST | `/placements` | Propose a placement | ProgramCoordinator |
| GET | `/placements/{id}` | Fetch a placement | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| GET | `/placements` | List placements | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| POST | `/placements/{id}/sign-waiver` | Participant signs the liability waiver | Participant |
| POST | `/placements/{id}/activate` | Activate a placement (PROPOSED → ACTIVE) | ProgramCoordinator |
| POST | `/placements/{id}/terminate` | Terminate a placement | ProgramCoordinator |
| POST | `/work-sessions` | Schedule a work session | SiteSupervisor, ProgramCoordinator |
| GET | `/work-sessions/{id}` | Fetch a work session | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| GET | `/work-sessions` | List work sessions | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| POST | `/work-sessions/{id}/check-in` | Check the participant in | SiteSupervisor |
| POST | `/work-sessions/{id}/check-out` | Check the participant out | SiteSupervisor |
| POST | `/work-sessions/{id}/verify` | Verify hours (VERIFIED/DISPUTED/REJECTED) | SiteSupervisor |
| POST | `/work-sessions/{id}/void` | Void a completed session | ProgramCoordinator, SiteSupervisor |
| POST | `/fee-conversions` | Request buying out outstanding hours | Participant, ProgramCoordinator |
| GET | `/fee-conversions/{id}` | Fetch a fee conversion | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| GET | `/fee-conversions` | List fee conversions | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| POST | `/fee-conversions/{id}/approve` | Approve a fee conversion (four-eyes) | ProgramCoordinator |
| POST | `/fee-conversions/{id}/deny` | Deny a fee conversion | ProgramCoordinator |
| POST | `/fee-conversions/{id}/pay` | Pay an approved fee conversion | Participant, ProgramCoordinator |
| POST | `/fee-conversions/{id}/reverse` | Reverse an approved/paid conversion | ProgramCoordinator |
| POST | `/compliance-actions` | File a WARNING or REPORT_BACK | CourtClerk |
| GET | `/compliance-actions/{id}` | Fetch a compliance action | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| GET | `/compliance-actions` | List compliance actions | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| GET | `/certificates/{id}` | Fetch a completion certificate | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |
| GET | `/certificates` | List completion certificates | CourtClerk, ProgramCoordinator, SiteSupervisor, Participant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_PAGINATION_INVALID` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_REFERRAL_NOT_ACTIVE` | 409 |
| `ERR_PLACEMENT_NOT_ACTIVE` | 409 |
| `ERR_WAIVER_REQUIRED` | 409 |
| `ERR_SITE_NOT_ACCEPTING` | 409 |
| `ERR_INSURANCE_INVALID` | 409 |
| `ERR_SUPERVISOR_SITE_MISMATCH` | 422 |
| `ERR_SELF_APPROVAL` | 403 |
| `ERR_SESSION_OVERLAP` | 409 |
| `ERR_SUPERVISOR_DOUBLE_BOOKED` | 409 |
| `ERR_SITE_CAPACITY_EXCEEDED` | 409 |
| `ERR_HOURS_EXCEED_OUTSTANDING` | 422 |
| `ERR_VERIFIED_HOURS_EXCEED_CLAIMED` | 422 |
| `ERR_CHECKOUT_BEFORE_CHECKIN` | 422 |
| `ERR_NO_REMAINING_HOURS` | 409 |
| `ERR_STALE_REFERRAL_VERSION` | 412 |
