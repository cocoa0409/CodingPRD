# NCAA Recruiting And NIL Compliance API — Product Requirements Document

## 1. Introduction

College athletics has become an environment in which scholarship economics, recruiting calendars, name-image-likeness (NIL) endorsement markets, the Transfer Portal, and bylaw enforcement against boosters all interact in ways that no single spreadsheet or shared inbox can track. The cost of a single mistake — an athlete enrolled before the Eligibility Center clears them, a NIL deal approved while the athlete is mid-investigation, a recruiting call placed inside a Dead Period — is no longer measured in apologies. It is measured in scholarship reductions, postseason bans, and vacated wins. Compliance staff at NCAA member institutions need a system of record that does not just store decisions, but enforces them in the order the bylaws actually require.

This document specifies the **NCAA Recruiting and NIL Compliance API**, a backend that governs the full lifecycle of a student-athlete's relationship with an institution: Eligibility Center adjudication, scholarship slot allocation under per-sport equivalency and roster caps, recruiting contact logging against the four NCAA calendar period types, NIL deal review (with fair-market valuation and pay-for-play classification), Transfer Portal entry and re-commitment, and a violation case file that supports investigation, appeal, and recidivism-weighted penalty scoring. The system is designed around **strict segregation of duties** — the recruiter who signs an athlete cannot adjudicate a deal she sponsors, and the compliance officer who substantiates a violation cannot also rule on its appeal — and around **deterministic time gating**, so that portal windows and appeal windows close on a server clock that can be advanced under test.

The audience for this PRD is the implementation team. Every field name in the request and response bodies, every state transition, and every error code referenced below is part of the system's testable contract. Where a calculation appears, the order of evaluation and rounding is part of the specification, not an implementation choice.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers identifying the acting principal: `X-User-ID` and `X-User-Role`. The sole exception is the read-side clock endpoint, which is open; the clock-advance endpoint still requires both headers. Requests missing either header on any endpoint that requires authentication are rejected with `ERR_AUTH_MISSING`. If `X-User-Role` is supplied but is not one of the five recognized role names listed below, the request is rejected with `ERR_AUTH_INVALID_ROLE`. A request that passes the header and role-name checks but targets an endpoint not permitted for that role under the RBAC matrix in §4 is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly five roles, spelled as follows:

- `ComplianceOfficer` — athletic department compliance staff. Adjudicates Eligibility Center decisions, NIL deals, and violation cases. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it (for example, as `reviewer_user_id` on a `ComplianceViolation` when the officer opens the investigation) but never compares it to any entity's `id`. Segregation of duties is enforced by comparing recorded `X-User-ID` values across successive transitions on the same case, not by joining against an officer table.
- `Coach` — sport-specific recruiter who offers scholarship slots and logs recruiting contacts. When `X-User-Role` is `Coach`, `X-User-ID` is likewise opaque; the server does not match it to any entity row.
- `Athlete` — the student-athlete acting on their own behalf. When `X-User-Role` is `Athlete`, `X-User-ID` is the `id` of the acting `Athlete`. Ownership checks on any resource that references an `Athlete` compare the resource's `athlete_id` field to `X-User-ID`; an Athlete who supplies someone else's `athlete_id` when submitting an NIL deal or entering the portal is rejected with `ERR_FORBIDDEN`.
- `Booster` — a registered supporter of a program. When `X-User-Role` is `Booster`, `X-User-ID` is opaque (it identifies a booster account, not an entity in this API); the server records it for audit but does not compare it to any entity's `id`. A Booster may submit NIL deals but cannot self-approve them.
- `Auditor` — read-everywhere with one write capability: filing violation reports. When `X-User-Role` is `Auditor`, `X-User-ID` is opaque and not tied to any persisted entity.

Two further auth-tier rules apply at the transition level rather than at the endpoint level. First, the same `X-User-ID` may never act on both sides of a step pair that requires independent review: the user who submits an NIL deal may not subsequently move it to `UNDER_REVIEW` or `APPROVED`, and the user who moved a `ComplianceViolation` from `REPORTED` to `INVESTIGATING` (and thereby became `reviewer_user_id`) may not later move that same case from `APPEALED` to `SUSTAINED` or `OVERTURNED`. Both situations are rejected with `ERR_SEGREGATION_OF_DUTIES`. Second, on a `ComplianceViolation` already in `INVESTIGATING`, the move to `SUBSTANTIATED` or to `DISMISSED` is restricted to the same officer who took the case (the caller's `X-User-ID` must equal `reviewer_user_id`) — this is a continuity-of-investigation rule, also rejected with `ERR_SEGREGATION_OF_DUTIES` when violated.

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

---

### 2.3. Pagination

List endpoints are paginated with two query parameters. The `limit` parameter declares the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter declares the number of items to skip and defaults to 0. List endpoints sort results by `created_at` in ascending order unless explicitly stated otherwise. The response `meta` object for list endpoints includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources carry a standard set of system-managed fields:

- `id` — a server-minted UUID string. The UUID is not prefixed with any type tag; the format is the bare RFC 4122 form.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at row creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — a non-negative integer that starts at 1 and increments by one on every mutation of the resource.

Two entity types are append-only logs and therefore carry only `id` and `created_at`; neither `updated_at` nor `version` is present on them: the `RecruitingCalendar` (an immutable window declaration) and the `RecruitingContact` (an immutable contact event log). Likewise, the `EligibilityRecord` is append-only: once decided, it cannot be edited; a second `EligibilityRecord` for the same `athlete_id` is rejected with `ERR_ELIGIBILITY_ALREADY_DECIDED`. Append-only resources do not bear `updated_at` or `version`.

When a state transition or cascade re-computes a derived field on a non-append-only resource (for example, refreshing `Program.total_equivalencies_used` or `Program.compliance_status`), that re-computation counts as a mutation: the affected resource's `updated_at` is refreshed and `version` is incremented.

### 2.5. Optimistic Concurrency Control

Any endpoint that mutates a specific resource by `id` — including every edit endpoint and every state-transition endpoint — accepts an optional `version` field in the request body. State-transition endpoints additionally require a `to_status` field in the body identifying the target state of the transition. When `version` is supplied, the server compares it to the stored `version` of the target resource. If they differ, the mutation is rejected with `ERR_VERSION_MISMATCH`. When `version` is omitted, the server processes the mutation without the concurrency check. The version check is evaluated after authentication, role, existence, and from-state checks, but before any business-rule validation: a stale request on a resource that is already in the wrong state still reports `ERR_INVALID_STATE`, not `ERR_VERSION_MISMATCH`.

### 2.6. Nested Resource Validation and Reference Resolution

The path identifiers `programId`, `athleteId`, `calendarId`, `slotId`, `contactId`, `dealId`, `entryId`, `recordId`, and `violationId` are validated **left-to-right**: the first identifier in the URL that does not resolve to a stored resource produces a `404` with `ERR_NOT_FOUND`, and the server does not look further down the path. The same rejection applies to foreign-key fields supplied in request bodies — references such as `athlete_id`, `program_id`, `related_athlete_id`, `related_deal_id`, and `destination_program_id` are resolved before any business validation runs; an unresolved body reference is reported as `ERR_REFERENCE_NOT_FOUND`. Body-payload checks for scalar shape (negative cents, GPA out of `[0.00, 4.00]`, `deliverables_hours <= 0`, `stated_value_cents <= 0`, `market_rate_cents_per_hour <= 0`, `fractional_equivalency` outside `[0.01, 1.00]` or not at two decimal places) are reported as `ERR_VALIDATION_FAILED` with HTTP 400.

### 2.7. Precision, Rounding, and Monetary Representation

Money is carried in **integer USD cents** end-to-end: `annual_value_cents`, `stated_value_cents`, `market_rate_cents_per_hour`, `fmv_calculated_cents`, `approved_value_cents`, and `nil_deal_lifetime_value_cents` are all integers. Intermediate computations in the fair-market valuation and the pay-for-play classification are performed in floating point with rounding applied only at the final step, half-up to the nearest whole cent.

Scholarship equivalencies are stored to two decimal places, half-up rounding, in the closed interval `[0.01, 1.00]`. Roster counts and penalty point totals are integers. Penalty point thresholds use inclusive comparisons: a `penalty_points_total` of exactly 10 places the program at `YELLOW`, and a total of exactly 20 places it at `RED`.

### 2.8. Validation Priority and Evaluation Order

When a single request potentially triggers more than one validation failure, the system reports the failure that appears earliest in the following priority ordering. Each rule is named together with the error it raises; the order is the order of evaluation, top to bottom:

1. **Auth header presence** — missing or empty `X-User-Role` or `X-User-ID` on any endpoint other than the read-side clock or clock-advance endpoint produces `ERR_AUTH_MISSING`.
2. **Role name validity** — `X-User-Role` must be one of `ComplianceOfficer`, `Coach`, `Athlete`, `Booster`, or `Auditor`; otherwise `ERR_AUTH_INVALID_ROLE`.
3. **Endpoint authorization** — the role permitted for the requested endpoint, per §4; otherwise `ERR_FORBIDDEN`.
4. **Path existence** — left-to-right resolution of path parameters; first miss yields `ERR_NOT_FOUND`.
5. **Body reference resolution** — every foreign-key field in the request body resolves; otherwise `ERR_REFERENCE_NOT_FOUND`.
6. **From-state validity** — the target resource is in a permitted from-state for the requested transition; otherwise `ERR_INVALID_STATE`.
7. **Optimistic concurrency** — if `version` was supplied in the body, it equals the stored value; otherwise `ERR_VERSION_MISMATCH`.
8. **Segregation of duties** — the caller's `X-User-ID` is permitted for this specific step; otherwise `ERR_SEGREGATION_OF_DUTIES`.
9. **Eligibility clearance** — the athlete's `eligibility_record_id` is set and its `decision` is `QUALIFIER` or `PARTIAL_QUALIFIER`, on transitions that require it; otherwise `ERR_ELIGIBILITY_NOT_CLEARED`.
10. **Amateur status** — for NIL approval transitions, `amateur_status` equals `AMATEUR`; otherwise `ERR_AMATEUR_STATUS_LOST`.
11. **Pay-for-play classification** — for NIL approval transitions, `pay_for_play_flag` is false; otherwise `ERR_PAY_FOR_PLAY_DETECTED`.
12. **Recruiting calendar permission** — for `RecruitingContact` creation, the contact is permitted under the calendar matrix; otherwise `ERR_CONTACT_NOT_PERMITTED`.
13. **Athlete availability for slot signing** — for `ScholarshipSlot` `OFFERED → SIGNED`, the athlete is not in `TRANSFER_PORTAL` or `INELIGIBLE`; otherwise `ERR_ATHLETE_NOT_AVAILABLE`.
14. **Portal window** — for portal `CONTACT_WINDOW → COMMITTED` or `CONTACT_WINDOW → WITHDRAWN`, the current clock is strictly less than `window_closes_at`; otherwise `ERR_PORTAL_WINDOW_CLOSED`.
15. **Appeal window** — for `ComplianceViolation` `SUBSTANTIATED → APPEALED`, the elapsed time since the `SUBSTANTIATED` transition is strictly less than 14 days; otherwise `ERR_APPEAL_WINDOW_CLOSED`.
16. **Scholarship cap** — projected `total_equivalencies_used` (after applying the current slot's `fractional_equivalency`) is less than or equal to `scholarship_cap_equivalencies`; otherwise `ERR_SCHOLARSHIP_CAP_EXCEEDED`. This applies to `ScholarshipSlot` `OFFERED → SIGNED` and to the recipient program in a Transfer Portal `CONTACT_WINDOW → COMMITTED` (and equivalently the Athlete `TRANSFER_PORTAL → COMMITTED`).
17. **Roster cap** — projected `active_roster_count + 1` is less than or equal to `roster_cap_count`; otherwise `ERR_ROSTER_CAP_EXCEEDED`. This applies to the Athlete `COMMITTED → ENROLLED` transition (and to the recipient program on portal `CONTACT_WINDOW → COMMITTED`, which itself cascades enrollment).
18. **Body shape constraints** — `fractional_equivalency` is between `0.01` and `1.00` inclusive at two decimal places, `deliverables_hours` is greater than zero, `stated_value_cents` is greater than zero, `market_rate_cents_per_hour` is greater than zero, and `core_gpa` is between `0.00` and `4.00` inclusive; otherwise `ERR_VALIDATION_FAILED`.
19. **Calendar window shape** — for `RecruitingCalendar` creation, `start_date` is strictly before `end_date` and the duration `end_date − start_date` is at least one day; otherwise `ERR_CALENDAR_WINDOW_INVALID`.
20. **Active portal-entry uniqueness** — for portal creation, the athlete has no existing `TransferPortalEntry` in `ENTERED` or `CONTACT_WINDOW`; otherwise `ERR_DUPLICATE_PORTAL_ENTRY`.
21. **Eligibility record uniqueness** — for `EligibilityRecord` creation, no record already exists for the athlete; otherwise `ERR_ELIGIBILITY_ALREADY_DECIDED`.

This ordering is load-bearing. A request that fails several of these simultaneously must surface the highest-priority error only.

### 2.9. Hierarchical Consistency and Cascade Semantics

A single state transition often mutates several entities. The cascade pattern is deterministic and synchronous: the primary transition's row is updated, then dependent rows are updated in the order listed in §3, then any aggregate fields (`Program.total_equivalencies_used`, `Program.active_roster_count`, `Program.penalty_points_total`, `Program.compliance_status`, `Athlete.nil_deal_lifetime_value_cents`) are recomputed. Every row touched during the cascade — primary, dependent, and program aggregate — has its `updated_at` refreshed and its `version` incremented if the resource type carries those fields.

Two cascades are bidirectional. When a `ComplianceViolation` flips `outcome` from `PENDING` to `SUSTAINED` with `severity` `LEVEL_I` and a `related_athlete_id` set, the implicated athlete moves `ENROLLED → INELIGIBLE` and every `APPROVED` `NILDeal` for that athlete is suspended. When that same violation later flips `outcome` to `CLEARED` via `OVERTURNED`, the athlete moves `INELIGIBLE → ENROLLED` and every deal that the original cascade had suspended is returned to `APPROVED` with its `approved_value_cents` unchanged.

### 2.10. Test-Driving the Logical Clock

The system carries an internal logical clock against which all time-gated transitions are evaluated: portal entry windows, portal expirations, and the 14-day appeal window. A read endpoint exposes the current clock, and an admin-only test-driving capability accepts a `to_timestamp` value and advances the clock to it. Advancing the clock evaluates and executes time-gated automatic transitions in a fixed deterministic order: first `TransferPortalEntry` `ENTERED → CONTACT_WINDOW` for every entry whose holding period has elapsed, then `ComplianceViolation` `SUBSTANTIATED → SUSTAINED` for every substantiated case whose appeal window has expired, then `TransferPortalEntry` `CONTACT_WINDOW → EXPIRED` for every entry whose `window_closes_at` has been crossed. The response from a clock advance returns the new `now` and an `auto_transitions` array enumerating every transition fired, with `entity`, `id`, `from`, and `to` per item.

## 3. Business Logic & Workflows

### 3.1. Founding a Program and Declaring the Recruiting Calendar

A `ComplianceOfficer` founds a `Program` by supplying the `institution_name`, the `sport` (one of `FOOTBALL`, `MENS_BASKETBALL`, `WOMENS_BASKETBALL`, `BASEBALL`, or `SOFTBALL`), the `division` (one of `DI`, `DII`, or `DIII`), the `scholarship_cap_equivalencies` (a number expressing the total scholarship equivalencies allowed for the sport — for example, 85.0 for FBS football, 13.0 for men's basketball), and the `roster_cap_count` (the maximum head-count on the active roster). On creation, the system initializes the program's `total_equivalencies_used` to zero, `active_roster_count` to zero, `penalty_points_total` to zero, and `compliance_status` to `GREEN`. The four derived program fields are recomputed automatically whenever any of their underlying inputs change; `compliance_status` follows the trailing-730-day rollup described in §3.7.

Before any recruiting contact can be logged for a program, its `RecruitingCalendar` must be declared. A `ComplianceOfficer` posts one or more calendar windows, each carrying a `program_id`, a `period_type` (one of `QUIET`, `CONTACT`, `DEAD`, or `EVALUATION`), an inclusive `start_date`, an exclusive `end_date`, and an optional free-text `note`. The window must be at least one day long and `start_date` must be strictly before `end_date`; either failure raises `ERR_CALENDAR_WINDOW_INVALID` with HTTP 400. `RecruitingCalendar` rows are immutable after creation and carry only `id` and `created_at`. When listing windows, callers may filter by `program_id`, by `period_type`, or by `contains_date` (any window whose half-open interval covers the supplied timestamp).

### 3.2. The Eligibility Center and Athlete Lifecycle

An `Athlete` is registered by a `ComplianceOfficer` or by a `Coach` with the prospect's `full_name`, `high_school`, and `graduation_year`. The new athlete starts in `PROSPECTIVE` status with `amateur_status` `AMATEUR`, `years_of_eligibility_remaining` equal to 4, and `current_program_id` null. The lifecycle covers five states — `PROSPECTIVE`, `COMMITTED`, `ENROLLED`, `TRANSFER_PORTAL`, and `INELIGIBLE` — with `ENROLLED` reachable both from `COMMITTED` and from `INELIGIBLE` (via violation overturn) or from `TRANSFER_PORTAL → COMMITTED` (the portal re-commit cycle).

Before a prospect can commit, the Eligibility Center must adjudicate. A `ComplianceOfficer` posts an `EligibilityRecord` containing `athlete_id`, `core_gpa` (4.00 scale, two decimals), `standardized_test_score` (a SAT-equivalent score from 400 to 1600, or −1 to denote a test-optional waiver request), `core_courses_completed` (must be at least 16), `decision` (one of `QUALIFIER`, `PARTIAL_QUALIFIER`, `NON_QUALIFIER`, or `INCOMPLETE`), and `decided_at` (the wall-clock timestamp of the decision). The record is immutable after creation. Posting it sets the athlete's `eligibility_record_id` to the new record's `id`. Attempting to post a second record for the same athlete is rejected with `ERR_ELIGIBILITY_ALREADY_DECIDED`.

Commitment — the `PROSPECTIVE → COMMITTED` transition — is the responsibility of a `ComplianceOfficer`, who supplies the destination `program_id`. The transition requires that the athlete's `eligibility_record_id` is set and the record's `decision` is `QUALIFIER` or `PARTIAL_QUALIFIER` (otherwise `ERR_ELIGIBILITY_NOT_CLEARED`), and that at least one `ScholarshipSlot` for this athlete already sits in `SIGNED` status for the same `program_id` (otherwise `ERR_NO_SIGNED_SLOT`). The transition's side effect is to set `current_program_id` to the supplied program.

Enrollment — `COMMITTED → ENROLLED` — likewise lives with a `ComplianceOfficer`. It requires that `current_program_id` is set and that a `SIGNED` slot exists matching both the athlete and that program. On enrollment, the system cascades: every `SIGNED` slot for this athlete at that program transitions to `ACTIVE`, with `activated_at` pinned to the transition timestamp; `years_of_eligibility_remaining` is initialized to 4 if it was null and otherwise preserved; and the program's `active_roster_count` and `total_equivalencies_used` are recomputed. The cascade is blocked if the post-enrollment `active_roster_count + 1` would exceed `roster_cap_count` — the failing slot's would-be `SIGNED → ACTIVE` transition raises `ERR_ROSTER_CAP_EXCEEDED`, which propagates up and aborts the enclosing `COMMITTED → ENROLLED` transition before any side effect lands.

### 3.3. Scholarship Slots: Offering, Signing, and Cap Enforcement

A `Coach` offers a scholarship slot by posting a `ScholarshipSlot` with `program_id`, `athlete_id`, `fractional_equivalency` (a number in the closed interval `[0.01, 1.00]` at two decimal places, representing the portion of a full scholarship granted under equivalency-sport rules), and `annual_value_cents` (the annual stated cash value in USD cents). The slot is created in `OFFERED` status.

A `Coach` then advances the slot from `OFFERED` to `SIGNED`. This transition has two gating preconditions evaluated in the §2.8 priority order. First, the athlete must have a posted `EligibilityRecord` whose `decision` is `QUALIFIER` or `PARTIAL_QUALIFIER`, otherwise `ERR_ELIGIBILITY_NOT_CLEARED`. Second, the program's `total_equivalencies_used` plus this slot's `fractional_equivalency` must be less than or equal to its `scholarship_cap_equivalencies`, otherwise `ERR_SCHOLARSHIP_CAP_EXCEEDED`. Additionally, a slot can only be signed for an athlete who is not currently in `TRANSFER_PORTAL` or `INELIGIBLE` (otherwise `ERR_ATHLETE_NOT_AVAILABLE`). On success, `signed_at` is pinned to the request timestamp and the program's `total_equivalencies_used` is recomputed. A coach may also walk an offer back via `OFFERED → WITHDRAWN`; this terminal transition takes no preconditions and produces no side effects.

The `SIGNED → ACTIVE` transition is never invoked directly. It happens only as part of the Athlete enrollment cascade described in §3.2, and it is the point at which `Program.total_equivalencies_used` reflects the active commitment. The cascade `ACTIVE → RELEASED` is similarly automatic: it fires when the holding athlete enters the Transfer Portal (see §3.4), at which point program equivalencies and roster count are recomputed against the now-released slot.

There is one direct path out of `ACTIVE` that is not cascade-driven: `ACTIVE → REVOKED`, performed by a `ComplianceOfficer`. It requires that a `ComplianceViolation` linked to this slot's `athlete_id` exists with `outcome` `SUSTAINED` and `severity` of either `LEVEL_I` or `LEVEL_II`; absent such a violation, the transition is rejected with `ERR_NO_SUSTAINED_VIOLATION`. Revocation recomputes the program's `total_equivalencies_used` and `active_roster_count`. The terminal states of a `ScholarshipSlot` are therefore `WITHDRAWN`, `RELEASED`, and `REVOKED`.

The scholarship-cap rule is the system's primary concurrency hotspot. When two `Coach` actors attempt to sign two slots for the same program simultaneously, and the sum of both `fractional_equivalency` values would push `total_equivalencies_used` above `scholarship_cap_equivalencies`, the system serializes on `Program.total_equivalencies_used` first-writer-wins: exactly one slot signs; the loser is rejected with `ERR_SCHOLARSHIP_CAP_EXCEEDED` because it evaluates the cap with the prior slot's equivalency already counted. The cap is never breached.

The aggregation that drives this is the `scholarship_slot_usage` rule. The program's `total_equivalencies_used` is the sum of `fractional_equivalency` taken across every `ScholarshipSlot` for that program whose `status` is `SIGNED` or `ACTIVE`; slots in `OFFERED`, `WITHDRAWN`, `RELEASED`, or `REVOKED` are excluded from the sum. The program's `active_roster_count` is the count of `Athlete` rows whose `status` is `ENROLLED` and whose `current_program_id` equals the program's `id`. The aggregation runs after every `ScholarshipSlot` state transition. Fractional equivalencies are carried to two decimal places, half-up. The roster-count check on `SIGNED → ACTIVE` (within the enrollment cascade) is the inclusive `active_roster_count + 1 <= roster_cap_count` form; an enrollment that would push the count to exactly `roster_cap_count` is permitted, but `roster_cap_count + 1` is not.

### 3.4. The Transfer Portal: Entry, Window, and Re-Commitment

An `Athlete` (acting on their own behalf, with `X-User-ID` equal to the athlete's `id`) or a `ComplianceOfficer` initiates a `TransferPortalEntry` by supplying `athlete_id` and a `reason` (one of `PLAYING_TIME`, `COACHING_CHANGE`, `FAMILY`, `ACADEMIC`, or `OTHER`). The athlete must currently be in `ENROLLED` and must have no `NILDeal` in `UNDER_REVIEW` status (a pending NIL review blocks portal entry with `ERR_PENDING_NIL_REVIEW`). The athlete also may not already have a `TransferPortalEntry` in `ENTERED` or `CONTACT_WINDOW` status; a duplicate active entry is rejected with `ERR_DUPLICATE_PORTAL_ENTRY`.

On successful creation, the entry stores `origin_program_id` (the athlete's `current_program_id` at this instant), pins `entered_at` to the request timestamp, computes `window_closes_at` per the `transfer_window_close` rule, and starts in `ENTERED` status. The window length depends on the athlete's `amateur_status` at the moment of entry: an `AMATEUR` athlete receives a 45-day window, an `AT_RISK` athlete receives a 30-day window, and a `FORFEITED` athlete receives zero days — meaning a forfeited athlete cannot enter the portal at all, and the creation attempt is rejected with `ERR_PORTAL_INELIGIBLE`. `window_closes_at` equals `entered_at` plus the window length expressed in hours (so 45 days resolves to 1080 hours, and 30 days resolves to 720 hours), carried to second precision.

The act of entering the portal cascades through several entities. The athlete moves `ENROLLED → TRANSFER_PORTAL`, and `current_program_id` is set to null. Every `ScholarshipSlot` for that athlete at the origin program whose `status` was `ACTIVE` transitions to `RELEASED`, freeing the program's equivalencies. `Program.total_equivalencies_used` and `Program.active_roster_count` on the origin program are recomputed.

A holding period applies before the recipient programs may contact the athlete. The entry sits in `ENTERED` for 24 hours and then automatically transitions to `CONTACT_WINDOW` when the logical clock reaches `entered_at + 24 hours`. This transition is fired by a clock advance and never by a direct API call. Inside the contact window, two competing exits are possible. The first is a re-commit: a `ComplianceOfficer` posts a `CONTACT_WINDOW → COMMITTED` transition supplying a `destination_program_id`. The transition requires that the current clock is strictly less than `window_closes_at` (otherwise `ERR_PORTAL_WINDOW_CLOSED`), that the destination program exists, that the destination program already has a `SIGNED` `ScholarshipSlot` for this athlete, and that the recipient program's projected `total_equivalencies_used` would remain at or under its `scholarship_cap_equivalencies` (otherwise `ERR_SCHOLARSHIP_CAP_EXCEEDED`). On success, `destination_program_id` is pinned on the entry, and the athlete's `current_program_id` is set to the destination; this in turn triggers the Athlete `TRANSFER_PORTAL → COMMITTED` transition, whose own preconditions echo the recipient program's cap check.

The second exit is a withdrawal: an `Athlete` (their own entry) or a `ComplianceOfficer` posts a `CONTACT_WINDOW → WITHDRAWN`. This too requires the current clock to be strictly less than `window_closes_at`. On success, the athlete is rolled back: `status` reverts `TRANSFER_PORTAL → COMMITTED` (note: not back to `ENROLLED` after the contact window has opened; the prior cascade already released the slot) and `current_program_id` is set back to `origin_program_id`. Because the original slot was already `RELEASED` by the entry cascade, the system does not automatically re-create it; if the origin program wishes to back-fill, a `ComplianceOfficer` must manually post a new `ScholarshipSlot`.

If neither exit fires before `window_closes_at`, the entry automatically transitions `CONTACT_WINDOW → EXPIRED` on the next clock advance whose target time crosses the threshold. An expired athlete remains in `TRANSFER_PORTAL` and is effectively a free agent; no further cascade applies on expiration.

A third path exits the portal early. An `Athlete` or a `ComplianceOfficer` may withdraw the entry directly out of `ENTERED` (before the holding period elapses). This `ENTERED → WITHDRAWN` transition has no precondition and rolls the athlete back to `ENROLLED` at the `origin_program_id`. As with the `CONTACT_WINDOW → WITHDRAWN` rollback, the released slot is not auto-resurrected; a fresh slot must be posted.

When a withdrawal and a clock-driven expiration race on the same entry, the system serializes first-writer-wins on `TransferPortalEntry.status`: exactly one terminal state lands, and the loser receives `ERR_INVALID_STATE` because the entry is already in `WITHDRAWN` or `EXPIRED`.

The `immediate_eligibility` flag on a `TransferPortalEntry` is computed only at `CONTACT_WINDOW → COMMITTED`, per the `transfer_immediate_eligibility` rule. Let `prior_transfers` be the number of prior `TransferPortalEntry` rows for the same athlete with `status` `COMMITTED` whose `created_at` precedes this entry's `created_at`, and let `years_attended` equal 4 minus the athlete's `years_of_eligibility_remaining`. The athlete has immediate eligibility under either of two disjoint conditions: `prior_transfers` is zero and `years_attended` is at least zero (the one-time transfer rule), or `prior_transfers` is exactly one and `years_attended` is at least three (the graduate-transfer exception). Otherwise `immediate_eligibility` is false. Re-enrollment via the portal also requires that the recipient program's projected `active_roster_count + 1` does not exceed `roster_cap_count` — two athletes attempting to commit to the same program when only one roster slot remains race on `Program.active_roster_count`, first-writer wins, and the loser is rejected with `ERR_ROSTER_CAP_EXCEEDED` before any mutation of `Athlete.current_program_id` lands.

### 3.5. NIL Deal Submission, Valuation, and Pay-for-Play Classification

An `Athlete` (their own deals), a `Booster`, or a `ComplianceOfficer` submits a `NILDeal` carrying `athlete_id`, `sponsor_name`, `sponsor_is_booster` (a boolean indicating whether the sponsor is a registered booster of the athlete's current program), `deal_category` (one of `ENDORSEMENT`, `APPEARANCE`, `SOCIAL_MEDIA_POST`, `AUTOGRAPH_SIGNING`, or `CAMP_INSTRUCTION`), `stated_value_cents` (the contract's nominal payment in USD cents), `deliverables_hours` (the hours of athlete time required), and `market_rate_cents_per_hour` (an independent market rate for comparable services at the athlete's market tier). On submission the deal starts in `SUBMITTED` status; `fmv_calculated_cents` and `pay_for_play_flag` are computed immediately, and `approved_value_cents` and `review_started_at` remain null. While the deal is still in `SUBMITTED`, the submitter (or any role permitted on the deal) may edit `deliverables_hours`, `market_rate_cents_per_hour`, and `stated_value_cents` — each such edit re-runs the fair-market and pay-for-play computations.

The fair-market valuation — the `nil_deal_fair_market_value` rule — is the deal's independent valuation. It begins with a base equal to `deliverables_hours` multiplied by `market_rate_cents_per_hour`. The base is then multiplied by a category multiplier whose value depends on `deal_category`: 1.20 for `ENDORSEMENT`, 1.10 for `APPEARANCE`, 1.00 for `SOCIAL_MEDIA_POST`, 0.90 for `AUTOGRAPH_SIGNING`, and 1.05 for `CAMP_INSTRUCTION`. The result is then multiplied by a booster factor: 0.80 when `sponsor_is_booster` is true (a more conservative valuation of booster-paid deals), and 1.00 otherwise. No rounding is applied between these three multiplications; the product is rounded to the nearest whole cent, half-up, only at the final step, and the rounded value is stored on the deal as `fmv_calculated_cents`.

The pay-for-play classification — the `nil_deal_pay_for_play` rule — is structurally distinct from valuation; the same deal can be priced at fair market and still trip the flag. The classification yields `pay_for_play_flag` true if **any** of the following three conditions is met, and false otherwise: (a) `sponsor_is_booster` is true and the ratio of `stated_value_cents` to the maximum of `fmv_calculated_cents` and 1 is at least 3.0, meaning a booster is paying at least three times the fair value; (b) `sponsor_is_booster` is true, `deal_category` is `CAMP_INSTRUCTION`, `deliverables_hours` is at most 1.0, and `stated_value_cents` is at least $10,000 expressed as cents (that is, at least 1,000,000 in `stated_value_cents`), capturing the token-deliverable structural test where a booster pays a large fee for a nominal one-hour camp; or (c) the athlete's `current_program_id` is null (the athlete is either prospective or in the portal between commitments) and `stated_value_cents` is at least $50,000 expressed as cents (that is, at least 5,000,000 in `stated_value_cents`), capturing inducement-grade payments to uncommitted athletes regardless of category. The ratio comparison uses inclusive `>=` semantics with double-precision floating point.

### 3.6. NIL Deal Review, Approval, Suspension, and Revocation

A `ComplianceOfficer` advances a deal from `SUBMITTED → UNDER_REVIEW`. The acting officer's `X-User-ID` must differ from the `X-User-ID` that submitted the deal — a submitter may never start their own deal's review — otherwise `ERR_SEGREGATION_OF_DUTIES`. On success, `review_started_at` is pinned to the request timestamp.

From `UNDER_REVIEW`, a `ComplianceOfficer` may approve or reject. Approval — `UNDER_REVIEW → APPROVED` — has three business preconditions in the §2.8 order: `pay_for_play_flag` must be false (otherwise `ERR_PAY_FOR_PLAY_DETECTED`); the athlete's `status` must be `COMMITTED` or `ENROLLED` (otherwise `ERR_ATHLETE_NOT_ENROLLED`); and the athlete's `amateur_status` must be `AMATEUR` (otherwise `ERR_AMATEUR_STATUS_LOST`). On success, `approved_value_cents` is pinned to the minimum of `stated_value_cents` and `fmv_calculated_cents` — the system caps approved compensation at fair market when the stated payment exceeds it, but honors the stated value when it falls below fair market. The athlete's `nil_deal_lifetime_value_cents` is recomputed as the sum of `approved_value_cents` across that athlete's deals whose `status` is `APPROVED`. Suspended and revoked deals are excluded from the lifetime sum.

Rejection — `UNDER_REVIEW → REJECTED` — is terminal and has no business preconditions beyond the priority-ordered ones in §2.8. From `APPROVED`, two non-terminal moves are possible. A `ComplianceOfficer` may suspend the deal manually (`APPROVED → SUSPENDED`), and the system itself will suspend on cascade when the athlete flips to `INELIGIBLE` (see §3.7). In either case, `approved_value_cents` is preserved on the row for audit, and `Athlete.nil_deal_lifetime_value_cents` is recomputed without this deal. A suspended deal returns to `APPROVED` either by manual reinstatement (a `ComplianceOfficer` posts `SUSPENDED → APPROVED`) or automatically when the underlying violation is overturned (cascade from athlete `INELIGIBLE → ENROLLED`). The reinstatement transition has business preconditions: `amateur_status` must be `AMATEUR` and `status` must be `COMMITTED` or `ENROLLED`. On reinstatement, the lifetime sum re-includes this deal.

The terminal exit from `APPROVED` is `APPROVED → REVOKED`, performed by a `ComplianceOfficer`. It requires that a linked `ComplianceViolation` whose `violation_type` is `NIL_COLLECTIVE_PAYFORPLAY` has reached `outcome` `SUSTAINED`. Revocation recomputes the athlete's `nil_deal_lifetime_value_cents` (excluding this deal) and counts `approved_value_cents` toward the program's impermissible-benefit total at the moment of revocation. `REJECTED` and `REVOKED` are the deal's two terminal states.

A race condition is consequential here: a `ComplianceOfficer` may attempt to approve a deal exactly while a violation cascade is flipping the same athlete to `INELIGIBLE`. The system serializes by reading `Athlete.amateur_status` and `Athlete.status` at the start of the approval transition under a row-level lock on the athlete; an approval that is in flight while the violation cascade is mutating the athlete blocks until the cascade lands, and then either succeeds (the deal is approved before the athlete flips, in which case it will be immediately suspended by the cascade's `APPROVED → SUSPENDED` step) or fails with `ERR_AMATEUR_STATUS_LOST`. The two states — an `APPROVED` deal on an `INELIGIBLE` athlete with `amateur_status` not equal to `AMATEUR` — never coexist.

### 3.7. Compliance Violations: Investigation, Appeal, and Penalty Scoring

A `ComplianceOfficer` or an `Auditor` files a `ComplianceViolation` carrying the implicated `program_id`, the `subject_type` (one of `BOOSTER`, `COACH`, `ATHLETE`, or `PROGRAM_ADMIN`), a free-text `subject_ref` (a booster name, a coach handle, an athlete id, etc.), the `violation_type` (one of `IMPERMISSIBLE_BENEFIT`, `RECRUITING_CONTACT`, `NIL_COLLECTIVE_PAYFORPLAY`, `ACADEMIC_FRAUD`, or `OTHER`), a `severity` (one of `LEVEL_I`, `LEVEL_II`, `LEVEL_III`, or `LEVEL_IV` per the NCAA Level scheme), and optionally `related_athlete_id` and `related_deal_id` foreign keys for the affected athlete and deal. The new case starts in `REPORTED` status with `outcome` `PENDING` and `penalty_points` zero.

A `ComplianceOfficer` moves the case `REPORTED → INVESTIGATING`. The acting officer must not be affiliated with the implicated program — the implementer enforces this via a header check; if it fails, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. The transition pins `reviewer_user_id` to the caller's `X-User-ID`. From `INVESTIGATING`, the same officer (the caller's `X-User-ID` must equal `reviewer_user_id`) advances the case to `SUBSTANTIATED` or `DISMISSED`; a different officer attempting either move is rejected with `ERR_SEGREGATION_OF_DUTIES`. A `DISMISSED` outcome immediately flips `outcome` to `CLEARED`.

A `SUBSTANTIATED` case is appealable for 14 days from the timestamp of its `SUBSTANTIATED` transition. A `Coach` or `ComplianceOfficer` may post `SUBSTANTIATED → APPEALED` within that window; an attempt after 14 days have elapsed is rejected with `ERR_APPEAL_WINDOW_CLOSED`. From `APPEALED`, the case resolves to either `SUSTAINED` or `OVERTURNED`, performed by a `ComplianceOfficer` whose `X-User-ID` differs from `reviewer_user_id` (the appeal must be heard by a different officer than the one who substantiated it; otherwise `ERR_SEGREGATION_OF_DUTIES`). `SUSTAINED` flips `outcome` to `SUSTAINED`; `OVERTURNED` flips `outcome` to `CLEARED`.

If the 14-day appeal window elapses without an `APPEALED` transition, the next clock advance auto-fires `SUBSTANTIATED → SUSTAINED`. The cascade effects of the auto-expire path are identical to the `APPEALED → SUSTAINED` path described next. The terminal states of a `ComplianceViolation` are `DISMISSED`, `SUSTAINED`, and `OVERTURNED`.

Two race conditions warrant explicit serialization. When two `ComplianceOfficer` actors attempt the `REPORTED → INVESTIGATING` move on the same case simultaneously, the system serializes first-writer-wins on `ComplianceViolation.status`: exactly one becomes `reviewer_user_id`; the loser receives `ERR_INVALID_STATE` because the case is no longer in `REPORTED`. The companion race covered in §3.4 — a portal withdrawal versus a clock-driven expiration — likewise resolves to `ERR_INVALID_STATE` for the loser.

The `violation_penalty_score` rule fires whenever a violation reaches `SUSTAINED` (both from `APPEALED → SUSTAINED` and from the auto-expire `SUBSTANTIATED → SUSTAINED` path). The case's `penalty_points` is computed as severity points multiplied by a recidivism multiplier, rounded half-up to the nearest integer after the multiplication. Severity points are 10 for `LEVEL_I`, 5 for `LEVEL_II`, 2 for `LEVEL_III`, and 1 for `LEVEL_IV`. The recidivism multiplier counts prior `SUSTAINED` violations against the same `program_id` whose `created_at` falls strictly before this case's `created_at` and on or after `this.created_at − 730 days`, excluding this case itself: a count of zero yields multiplier 1.0; a count of exactly one yields 1.5; a count of two or more yields 2.0. While `outcome` is anything other than `SUSTAINED`, `penalty_points` is zero.

The `program_compliance_posture` rule rolls penalty points up to the program after every change in any violation's `outcome` to `SUSTAINED` or `CLEARED`. The program's `penalty_points_total` is the sum of `penalty_points` across all `ComplianceViolation` rows for that program whose `outcome` is `SUSTAINED` and whose `created_at` falls on or after `now() − 730 days`. The program's `compliance_status` is then `RED` if `penalty_points_total` is at least 20, `YELLOW` if it is at least 10 and strictly less than 20, and `GREEN` otherwise. Boundaries are inclusive on the lower side: a total of exactly 10 lands at `YELLOW`, and a total of exactly 20 lands at `RED`.

When a sustained violation is `LEVEL_I` and carries a `related_athlete_id`, the system cascades immediately on the `SUSTAINED` outcome flip. The implicated athlete moves `ENROLLED → INELIGIBLE`. The athlete's `amateur_status` is updated by the same cascade: `FORFEITED` when the severity is `LEVEL_I`, and `AT_RISK` when the severity is `LEVEL_II`. Every `NILDeal` for that athlete whose `status` is `APPROVED` is transitioned to `SUSPENDED`, and `approved_value_cents` is preserved on each suspended deal so that the lifetime audit trail remains reconstructable. Additionally, if the sustained violation's `violation_type` is `NIL_COLLECTIVE_PAYFORPLAY` and `related_deal_id` is set, the linked deal becomes eligible for the manual `APPROVED → REVOKED` action described in §3.6.

When a sustained violation that previously caused an athlete to flip `INELIGIBLE` is later `OVERTURNED`, the cascade is reversed. The athlete moves `INELIGIBLE → ENROLLED`, `amateur_status` is restored to `AMATEUR`, and every deal that was suspended by the original cascade returns to `APPROVED` with its `approved_value_cents` unchanged. The reinstatement restores the prior approved set exactly; the pinning of `approved_value_cents` at the original approval moment is what makes this audit-clean.

### 3.8. Recruiting Contacts and the Calendar Permission Matrix

A `Coach` logs a recruiting contact by posting a `RecruitingContact` with `program_id`, `athlete_id`, `contact_type` (one of `PHONE_CALL`, `IN_PERSON_OFF_CAMPUS`, `IN_PERSON_ON_CAMPUS`, `TEXT_MESSAGE`, or `EVALUATION`), and `contact_at` (the wall-clock timestamp of the contact, in UTC). The contact is an append-only event log; rows carry only `id` and `created_at`, and there is no edit endpoint.

The system resolves `contact_period_type` from the program's declared `RecruitingCalendar` windows per the `recruiting_contact_permitted` rule. Candidate windows are those `RecruitingCalendar` rows for the same `program_id` whose `start_date` is less than or equal to `contact_at` (inclusive) and whose `end_date` is strictly greater than `contact_at` (exclusive) — the windows are half-open intervals. If no window contains the timestamp, `contact_period_type` defaults to `DEAD`. If multiple windows overlap and all contain the timestamp, the most restrictive period type wins: in decreasing order of restrictiveness, `DEAD` outranks `CONTACT`, `CONTACT` outranks `EVALUATION`, and `EVALUATION` outranks `QUIET`. The resolved `contact_period_type` is stored on the row.

The `was_permitted` boolean is then derived from the period type and the contact modality, by this matrix:

- During a `CONTACT` period, every modality is permitted: `PHONE_CALL`, `IN_PERSON_OFF_CAMPUS`, `IN_PERSON_ON_CAMPUS`, `TEXT_MESSAGE`, and `EVALUATION` are all allowed.
- During a `QUIET` period, `PHONE_CALL`, `IN_PERSON_ON_CAMPUS`, and `TEXT_MESSAGE` are permitted; `IN_PERSON_OFF_CAMPUS` and `EVALUATION` are not.
- During a `DEAD` period, every modality is forbidden.
- During an `EVALUATION` period, `PHONE_CALL`, `TEXT_MESSAGE`, and `EVALUATION` are permitted; `IN_PERSON_OFF_CAMPUS` and `IN_PERSON_ON_CAMPUS` are not.

If `was_permitted` is false, the contact is rejected with `ERR_CONTACT_NOT_PERMITTED` and no row is persisted. Listing recruiting contacts supports filtering by `program_id`, by `athlete_id`, by `contact_period_type`, and by an `after` / `before` time range against `contact_at`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (a Program, an Athlete, an EligibilityRecord, a ScholarshipSlot, a RecruitingCalendar window, a RecruitingContact, a NILDeal, a TransferPortalEntry, a ComplianceViolation) return `201 Created`. Operations that modify an existing resource, including all state transitions and the NIL deal `PATCH`, return `200 OK`. The two clock endpoints both return `200 OK`. Errors follow the HTTP status codes listed in §5.

| Method | Path                                              | Description                                                             | Authorized Role(s)                                  |
| ------ | ------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------- |
| POST   | `/programs`                                       | Create a Program (institution + sport)                                  | `ComplianceOfficer`                                 |
| GET    | `/programs/{programId}`                           | Get a Program (with derived totals)                                     | `ComplianceOfficer`, `Coach`, `Auditor`             |
| GET    | `/programs`                                       | List Programs (filter by `sport`, `division`, `compliance_status`)      | `ComplianceOfficer`, `Coach`, `Auditor`             |
| POST   | `/recruiting-calendars`                           | Declare a calendar window for a program                                 | `ComplianceOfficer`                                 |
| GET    | `/recruiting-calendars/{calendarId}`              | Get one calendar window                                                 | `ComplianceOfficer`, `Coach`, `Auditor`             |
| GET    | `/recruiting-calendars`                           | List calendar windows (filter by `program_id`, `period_type`, `contains_date`) | `ComplianceOfficer`, `Coach`, `Auditor`     |
| POST   | `/athletes`                                       | Register a prospective athlete                                          | `ComplianceOfficer`, `Coach`                        |
| GET    | `/athletes/{athleteId}`                           | Get an athlete                                                          | `ComplianceOfficer`, `Coach`, `Athlete`, `Auditor`  |
| GET    | `/athletes`                                       | List athletes (filter by `status`, `current_program_id`, `amateur_status`) | `ComplianceOfficer`, `Coach`, `Auditor`          |
| POST   | `/athletes/{athleteId}/state`                     | Transition an athlete                                                   | `ComplianceOfficer`                                 |
| POST   | `/eligibility-records`                            | Post an Eligibility Center decision (immutable)                         | `ComplianceOfficer`                                 |
| GET    | `/eligibility-records/{recordId}`                 | Get an eligibility record                                               | `ComplianceOfficer`, `Auditor`                      |
| POST   | `/scholarship-slots`                              | Offer a scholarship slot                                                | `Coach`                                             |
| GET    | `/scholarship-slots/{slotId}`                     | Get a scholarship slot                                                  | `ComplianceOfficer`, `Coach`, `Auditor`             |
| GET    | `/scholarship-slots`                              | List scholarship slots (filter by `program_id`, `athlete_id`, `status`) | `ComplianceOfficer`, `Coach`, `Auditor`             |
| POST   | `/scholarship-slots/{slotId}/state`               | Transition a scholarship slot                                           | `Coach`, `ComplianceOfficer`                        |
| POST   | `/recruiting-contacts`                            | Log a recruiting contact event                                          | `Coach`                                             |
| GET    | `/recruiting-contacts/{contactId}`                | Get a recruiting contact                                                | `ComplianceOfficer`, `Coach`, `Auditor`             |
| GET    | `/recruiting-contacts`                            | List recruiting contacts (filter by `program_id`, `athlete_id`, `contact_period_type`, `after`, `before`) | `ComplianceOfficer`, `Coach`, `Auditor` |
| POST   | `/nil-deals`                                      | Submit an NIL deal for review                                           | `Athlete`, `Booster`, `ComplianceOfficer`           |
| GET    | `/nil-deals/{dealId}`                             | Get an NIL deal                                                         | `ComplianceOfficer`, `Coach`, `Athlete`, `Auditor`  |
| GET    | `/nil-deals`                                      | List NIL deals (filter by `athlete_id`, `status`, `pay_for_play_flag`)  | `ComplianceOfficer`, `Coach`, `Auditor`             |
| PATCH  | `/nil-deals/{dealId}`                             | Edit an NIL deal (only while `SUBMITTED`)                               | `Athlete`, `Booster`, `ComplianceOfficer`           |
| POST   | `/nil-deals/{dealId}/state`                       | Transition an NIL deal                                                  | `ComplianceOfficer`                                 |
| POST   | `/transfer-portal-entries`                        | Enter the Transfer Portal                                               | `Athlete`, `ComplianceOfficer`                      |
| GET    | `/transfer-portal-entries/{entryId}`              | Get a portal entry                                                      | `ComplianceOfficer`, `Coach`, `Athlete`, `Auditor`  |
| GET    | `/transfer-portal-entries`                        | List portal entries (filter by `status`, `athlete_id`, `origin_program_id`) | `ComplianceOfficer`, `Coach`, `Auditor`         |
| POST   | `/transfer-portal-entries/{entryId}/state`        | Transition a portal entry                                               | `ComplianceOfficer`, `Athlete`                      |
| POST   | `/violations`                                     | Report a violation                                                      | `ComplianceOfficer`, `Auditor`                      |
| GET    | `/violations/{violationId}`                       | Get a violation                                                         | `ComplianceOfficer`, `Coach`, `Auditor`             |
| GET    | `/violations`                                     | List violations (filter by `program_id`, `status`, `outcome`, `severity`) | `ComplianceOfficer`, `Coach`, `Auditor`           |
| POST   | `/violations/{violationId}/state`                 | Transition a violation                                                  | `ComplianceOfficer`, `Coach`                        |
| GET    | `/_clock`                                         | Read the system clock                                                   | `ComplianceOfficer`, `Coach`, `Athlete`, `Booster`, `Auditor` |
| POST   | `/_clock/advance`                                 | Advance the system clock; fires time-gated transitions                  | `ComplianceOfficer`, `Auditor`                      |

## 5. Error Code Catalogue

| Error ID                          | HTTP Status Code |
| --------------------------------- | ---------------- |
| `ERR_AUTH_MISSING`                | 401              |
| `ERR_AUTH_INVALID_ROLE`           | 403              |
| `ERR_FORBIDDEN`                   | 403              |
| `ERR_SEGREGATION_OF_DUTIES`       | 403              |
| `ERR_NOT_FOUND`                   | 404              |
| `ERR_REFERENCE_NOT_FOUND`         | 404              |
| `ERR_INVALID_STATE`               | 409              |
| `ERR_VERSION_MISMATCH`            | 409              |
| `ERR_VALIDATION_FAILED`           | 400              |
| `ERR_ELIGIBILITY_NOT_CLEARED`     | 409              |
| `ERR_ELIGIBILITY_ALREADY_DECIDED` | 409              |
| `ERR_NO_SIGNED_SLOT`              | 409              |
| `ERR_ATHLETE_NOT_AVAILABLE`       | 409              |
| `ERR_ATHLETE_NOT_ENROLLED`        | 409              |
| `ERR_AMATEUR_STATUS_LOST`         | 409              |
| `ERR_PAY_FOR_PLAY_DETECTED`       | 409              |
| `ERR_PENDING_NIL_REVIEW`          | 409              |
| `ERR_SCHOLARSHIP_CAP_EXCEEDED`    | 409              |
| `ERR_ROSTER_CAP_EXCEEDED`         | 409              |
| `ERR_CONTACT_NOT_PERMITTED`       | 409              |
| `ERR_CALENDAR_WINDOW_INVALID`     | 400              |
| `ERR_PORTAL_WINDOW_CLOSED`        | 409              |
| `ERR_PORTAL_INELIGIBLE`           | 409              |
| `ERR_DUPLICATE_PORTAL_ENTRY`      | 409              |
| `ERR_APPEAL_WINDOW_CLOSED`        | 409              |
| `ERR_NO_SUSTAINED_VIOLATION`      | 409              |
