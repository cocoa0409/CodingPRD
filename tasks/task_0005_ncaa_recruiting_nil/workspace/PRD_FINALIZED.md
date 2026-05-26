# NCAA Recruiting and NIL Compliance API — Product Requirements Document

## 1. Introduction

The NCAA Recruiting and NIL Compliance API provides the system of record for the four overlapping streams of work that govern an intercollegiate athletics program: certifying student-athlete eligibility, controlling the recruiting calendar, allocating scholarship slots under hard NCAA caps, and adjudicating endorsement deals and booster violations. Each of these streams is operated by a different group — eligibility evaluators, compliance officers, recruiting coaches, NIL reviewers, and the athletes themselves — and each operates under regulatory deadlines that, when missed, are not recoverable. The system's purpose is to make those deadlines explicit, to refuse actions that would put a program out of compliance, and to keep the slot, eligibility, and sanction state of every program internally consistent at all times.

A defining property of the domain is that decisions made in one stream cascade immediately into the others. An eligibility denial pulls every outstanding scholarship offer to that athlete out of the pipeline. A sustained booster incident, if it carries enough weight, can suspend a program's ability to send any new offer at all and forcibly retract offers already in transit. A NIL deal cannot move toward approval unless the underlying athlete has been certified. The API exposes each of these workflows as a sequence of explicit state transitions guarded by preconditions, so the boundary between "compliant" and "non-compliant" is never the product of a side calculation — it is the boundary between two named states.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to every operation in the API. The remaining business-specific rules — slot accounting, the recruiting-period calendar, NIL tier classification, the booster penalty ladder, the transfer-portal window — are documented in §3 under the workflow that exercises them.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which they are acting. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is not on the authorization list for the targeted endpoint is rejected with `ERR_UNAUTHORIZED` (403).

The system recognizes five roles. `ComplianceOfficer` is the NCAA-side administrator who creates programs, opens and resolves booster investigations, sets the recruiting calendar, matches transfer-portal entrants to destination programs, and operates the deterministic clock and the portal-expiration sweep. `Coach` is the recruiting coach who logs contacts and authors and dispatches scholarship offers for a single program. `StudentAthlete` is the recruited or enrolled athlete who proposes NIL deals, accepts or declines offers, enters and withdraws from the transfer portal. `NILReviewer` is the segregation-of-duty-bound deal reviewer who moves NIL deals through the submission, revision, approval, and rejection states. `EligibilityCenter` is the role that submits, approves, and denies eligibility certifications.

The bindings between `X-User-ID` and the persisted entity model differ by role and are load-bearing for the ownership and segregation-of-duty checks elsewhere in this document. When `X-User-Role` is `StudentAthlete`, `X-User-ID` is the `id` of the acting `StudentAthlete` row; ownership checks on any resource that references a `StudentAthlete` compare the resource's `student_athlete_id` (or, on a scholarship-offer accept or decline, the offer's `student_athlete_id`) to `X-User-ID`. When `X-User-Role` is any of `ComplianceOfficer`, `Coach`, `NILReviewer`, or `EligibilityCenter`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it — for example, a coach's `X-User-ID` is recorded on `RecruitingContact.coach_user_id` and the NIL deal segregation-of-duties check compares the approver's `X-User-ID` to the `X-User-ID` of every previous submitter or revision-requester of that deal — but the server does not compare it to any entity's `id`. For a `Coach`, affiliation to a specific program is established by the `program_id` carried in the request body for contact and offer creation and is pinned thereafter on `ScholarshipOffer.program_id`; later coach-driven transitions on that offer require the acting `X-User-ID` to match the `X-User-ID` that stamped the offer (i.e. the coach must belong to `offer.program_id`), and a mismatch is rejected with `ERR_COACH_PROGRAM_MISMATCH`.

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

All list endpoints accept the query parameters `limit` and `offset`. The `limit` parameter specifies the maximum number of items to return; if omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. List endpoints return resources sorted by `created_at` ascending unless otherwise specified.

Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource in the system — `Program`, `Period`, `StudentAthlete`, `EligibilityCertification`, `RecruitingContact`, `ScholarshipOffer`, `NILDeal`, `TransferPortalEntry`, and `BoosterIncident` — carries the same four system-managed fields:

- `id` (string): a server-minted UUID. The id has no type prefix; it is the bare UUID.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, pinned at row creation and never modified.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed every time any field on the resource is mutated, including by cascading writes from another entity's transition.
- `version` (integer): begins at 1 on creation and is incremented by 1 on every mutation of the row, including mutations driven by cascades from elsewhere in the system. `version` is the value used by the optimistic-concurrency-control checks in §2.5.

Any time a write to one entity also mutates another entity as a side effect — a cascaded scholarship withdrawal driven by an eligibility denial, a slot rebalance on a program driven by an offer-status change, a flip of `StudentAthlete.in_transfer_portal` driven by a portal sweep — the secondary entity's `updated_at` is refreshed and its `version` is incremented exactly as it would be on a direct write.

### 2.5. Optimistic Concurrency Control

Three operations in this API require a client-supplied version field; all other write operations do not. The version field is not optional on these three operations — its absence is treated as a malformed request (`ERR_INVALID_REQUEST`), and its presence with a value that does not match the targeted entity's current `version` causes the request to be rejected without any state change.

- Sending a scholarship offer (i.e. the action that transitions `ScholarshipOffer.status` from `DRAFT` to `SENT`) requires `expected_program_version` in the request body, matching the current `version` of the offer's parent `Program`. The Program is the parent of the OCC check because the operation increments `Program.slots_committed` against `Program.scholarship_slot_cap`, and if another writer has just sent an offer that consumed the last open slot, the current writer's view of the slot count is stale. A mismatch is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412).
- Matching a transfer-portal entry to a destination program requires `expected_transferportalentry_version` in the request body, matching the current `version` of the targeted `TransferPortalEntry`. The entry is the parent of the OCC check because the operation installs a `matched_program_id` on it, and a stale matcher could otherwise install a destination on an entry whose `ENTERED` state no longer holds (because the athlete withdrew or because a clock-driven sweep already expired it). A mismatch is rejected with `ERR_STALE_ENTRY_VERSION` (HTTP 412).
- Sustaining a booster incident requires `expected_boosterincident_version` in the request body, matching the current `version` of the targeted `BoosterIncident`. The incident is the parent of the OCC check because the sustain action stamps `severity_weight` on the row and feeds the program-penalty recompute; a second sustainer working from a stale view would silently overwrite the weight stamped by the first and double-trigger the penalty cascade. A mismatch is rejected with `ERR_STALE_INCIDENT_VERSION` (HTTP 412).

These three rules are framed purely in terms of stale versions and the mismatch is detected on the row itself; the rejection does not depend on any specific timing relationship between two requests.

### 2.6. Validation Ordering

When an endpoint is guarded by more than one of the validation rules in this document, the rules are evaluated in a fixed priority order, and the first violation encountered is the one reported. The order is: authentication of the request headers (`ERR_UNAUTHENTICATED`); authorization of the role for the endpoint (`ERR_UNAUTHORIZED`); resolution of every `id` segment in the URL path, left-to-right (`ERR_NOT_FOUND`); resolution of every foreign-key field carried in the request body (`ERR_NOT_FOUND`); the state-machine precondition that the target row is in a state from which the requested transition is legal (`ERR_INVALID_STATE`); the optimistic-concurrency check on the `expected_*_version` field for the three endpoints listed in §2.5 (`ERR_STALE_PROGRAM_VERSION`, `ERR_STALE_ENTRY_VERSION`, or `ERR_STALE_INCIDENT_VERSION`); then the business-safety, business-referential, business-constraint, business-fiscal, and business-temporal rules described under their owning workflows in §3; and finally, body-shape validation of types and required fields (`ERR_INVALID_REQUEST`).

Where two business rules apply to the same endpoint, the document calls out the relative ordering inline. In particular: on the recruiting-contact create endpoint, contact-in-a-`DEAD`-period is checked before contact-in-a-`QUIET`-period-with-the-wrong-channel, which is checked before contact-in-a-gap-between-periods. On the scholarship-offer send endpoint, the cross-entity eligibility check (the athlete must be `CERTIFIED`) is checked before the slot-cap boundary check. On the NIL deal approve endpoint, the segregation-of-duties check is checked before the high-value-deal-under-sanction check.

### 2.7. Nested Resource Retrieval

Several endpoints embed more than one identifier in their URL path — for example, the recruiting-calendar period endpoints take both a program id and (on read) a period id, and several action endpoints address a child entity via its own id under a top-level namespace. The system validates these identifiers in strict left-to-right order: if the first identifier in the path does not resolve to an existing row, the request is rejected with `ERR_NOT_FOUND` before the system attempts to resolve any subsequent identifier. The same rule applies to foreign-key identifiers carried in the request body — for example, the `program_id`, `student_athlete_id`, and `matched_program_id` fields — which are resolved against their target entities and rejected with `ERR_NOT_FOUND` if they do not exist.

### 2.8. Calendar and Time Semantics

All timestamps in the system are ISO 8601 UTC. Periods on the recruiting calendar are interpreted as half-open intervals: `starts_at` is inclusive, `ends_at` is exclusive. A contact whose `contact_at` is exactly equal to a period's `ends_at` does not fall within that period; it falls within whatever period (if any) begins at that same instant.

For deterministic time-gated tests, the system exposes a clock-setting capability (`ComplianceOfficer`-only). Setting the clock pins `current_utc` to the supplied `to_iso8601` value; subsequent operations that read the current time — period selection for a recruiting contact, the transfer-portal window check, and the portal-expiration sweep — read from this pinned clock. The transfer-portal expiration is itself driven by a separate, idempotent sweep capability that scans for any `TransferPortalEntry` whose `status` is `ENTERED` and whose `window_closes_at` is at or before `current_utc`, and transitions each such entry to `EXPIRED`; the sweep returns the resulting `expired_count` and the list of `expired_entry_ids`.

### 2.9. Slot Accounting Precision

All slot counts — `Program.slots_committed`, `Program.slots_projected`, `Program.scholarship_slot_cap` — are integer counts of `ScholarshipOffer` rows and are not subject to any rounding rule. `scholarship_slot_cap` is supplied at program creation and is constrained to be at least 1 and at most 130. Slot counts are recomputed at every event that could change them: every `ScholarshipOffer` state transition, every `EligibilityCertification` denial cascade, and every booster-incident sustain that escalates the program to `POSTSEASON_BAN`.

### 2.10. Monetary Precision

All monetary values in the API are integer cents. `ScholarshipOffer.annual_value_cents`, `NILDeal.gross_value_cents`, `NILDeal.net_value_cents`, and `BoosterIncident.alleged_value_cents` are all non-negative integer cent counts, never floating-point dollars. The single computation that produces a derived cent value — the net value of a NIL deal — multiplies the gross by one minus the agent fee fraction and then rounds to the nearest cent using banker's rounding (round half to even). This rounding step is applied to the cent value before any tier boundary is evaluated; details of the tier calculation appear with the NIL deal lifecycle in §3.

## 3. Business Logic & Workflows

### 3.1. Programs and the Recruiting Calendar

The `Program` is the top-level organizing entity for everything else in this API. A `ComplianceOfficer` creates a program by supplying a `sport_code` (one of `FOOTBALL`, `MBB`, `WBB`, `BASEBALL`, or `SOFTBALL`), a `school_name`, and a `scholarship_slot_cap`. The cap is the NCAA-imposed ceiling on the number of scholarships the program may have simultaneously committed and must be supplied as an integer no smaller than 1 and no larger than 130. On creation, the program's `slots_committed` and `slots_projected` are both initialized to 0, its `penalty_tier` is initialized to `NONE`, and its `version` is set to 1.

Within each program, a `ComplianceOfficer` defines a recruiting calendar as an ordered series of `Period` rows. A period is created by supplying a `period_type` — one of `CONTACT`, `QUIET`, or `DEAD` — together with `starts_at` and `ends_at`. Each period must describe a forward-going interval, i.e. its `starts_at` must be strictly earlier than its `ends_at`; an inverted or zero-length interval is rejected with `ERR_INVALID_INTERVAL`. Periods within the same program may not overlap: if a newly supplied period's half-open interval `[starts_at, ends_at)` intersects the interval of any existing period for that same `program_id`, the create is rejected with `ERR_PERIOD_OVERLAP`. Adjacency is permitted — a new period whose `starts_at` is exactly equal to an existing period's `ends_at` is accepted, because the existing period excludes its endpoint. The merest overlap, including a one-cent overlap, is rejected.

A coach may inspect the existing calendar before logging a contact, and the system exposes per-program list and read endpoints for periods filterable by `period_type`. Periods do not transition through states; once created they are immutable except for the `updated_at` and `version` mechanics that apply to every entity.

### 3.2. Student-Athlete Intake and Eligibility Certification

Athletes enter the system when a `ComplianceOfficer` creates a `StudentAthlete` row, supplying a `full_name`, a `sport_code` (drawn from the same enumeration as `Program.sport_code`), a `gpa` reported as a core-course grade-point average with three decimal places between 0.000 and 4.000 inclusive, and an optional `amateurism_flag` that defaults to `true` when omitted. On creation, the athlete's `eligibility_status` is `UNCERTIFIED`, `in_transfer_portal` is `false`, `enrolled_program_id` is null, and `version` is 1.

Certification is the exclusive province of the `EligibilityCenter`. A reviewer initiates certification by submitting an `EligibilityCertification` row referencing a `student_athlete_id`. On submission, the system snapshots the athlete's current values into `gpa_at_review` and `amateurism_at_review`, frozen on the certification thereafter so that subsequent edits to the athlete do not retroactively alter a pending review. The certification is created with `status` `PENDING` and `version` 1; `denial_reason` is null at this point.

A pending certification has two terminal outcomes. Approving the certification — transitioning `status` from `PENDING` to `APPROVED` — requires that the snapshotted `gpa_at_review` be at least 2.300 (the NCAA core-GPA floor) and that `amateurism_at_review` be `true`. On approval, the athlete's `eligibility_status` flips from `UNCERTIFIED` to `CERTIFIED`, the athlete's `updated_at` is refreshed and its `version` is incremented, and the certification's own `version` is incremented. Denying the certification — transitioning `status` from `PENDING` to `DENIED` — requires a `denial_reason` drawn from `GPA_BELOW_MIN`, `AMATEURISM_LOST`, or `INCOMPLETE_RECORDS`; this field is optional on submission but mandatory at the moment of denial.

Denial is also the originating event for the most consequential cascade in the system. When a certification transitions `PENDING → DENIED`, the athlete's `eligibility_status` flips to `INELIGIBLE` and every outstanding scholarship offer for that athlete is forcibly withdrawn by the system. Specifically: every `ScholarshipOffer` for that `student_athlete_id` whose `status` is `DRAFT` or `SENT` auto-transitions to `WITHDRAWN`; each cascade-driven withdrawal increments the offer's `version` and refreshes its `updated_at`. For each offer whose prior status was `SENT`, the cascade also decrements the issuing program's `slots_committed` by 1, refreshes the program's `updated_at`, and increments the program's `version` — this is the compensating side of the slot accounting and ensures that a denied athlete never continues to count against a program's cap. For each offer whose prior status was `DRAFT`, no slot change occurs because a `DRAFT` offer was never committed in the first place. The certification itself also bumps its own `version` exactly once.

### 3.3. Recruiting Contacts and the Calendar

Within an active program, a `Coach` logs each recruiting contact through a payload identifying the `program_id`, the recruited `student_athlete_id`, the coach's own `coach_user_id`, the contact's `contact_at` timestamp, and the `channel` of communication — one of `IN_PERSON`, `PHONE`, `DM`, or `EMAIL`. The athlete's `sport_code` must match the program's `sport_code`; this is a referential consequence of the program's exclusive ownership of its recruiting roster.

The legality of any contact depends entirely on where `contact_at` falls in the program's recruiting calendar. The system performs three calendar-related checks against the program's `Period` rows, evaluated in this fixed order. First, if `contact_at` falls inside a period whose `period_type` is `DEAD`, the contact is rejected with `ERR_DEAD_PERIOD_CONTACT`; all contact is prohibited during a dead period regardless of channel. Second, if `contact_at` falls inside a period whose `period_type` is `QUIET`, only in-person contact is permitted; a quiet-period contact whose `channel` is anything other than `IN_PERSON` is rejected with `ERR_QUIET_PERIOD_VIOLATION`. Third, if `contact_at` does not fall inside any period at all — the program's calendar has a gap at that instant — the contact is implicitly prohibited and is rejected with `ERR_OUTSIDE_RECRUITING_WINDOW`.

When all three calendar checks pass, the contact is created. The system computes which period contains `contact_at` (using the half-open `[starts_at, ends_at)` semantics from §2.8) and pins that period's type onto the contact as `period_type_at_contact`; this field is therefore always one of `CONTACT` or `QUIET` on a successfully created contact, never `DEAD`, and is computed by the system rather than supplied by the coach. The contact is created with `version` 1. List endpoints for contacts are filterable by `program_id`, `student_athlete_id`, and `coach_user_id`.

### 3.4. Scholarship Offers and Slot Accounting

The scholarship-offer lifecycle is the heart of the slot-accounting model. A `Coach` creates an offer by supplying the `program_id`, the recipient's `student_athlete_id`, and the offer's `annual_value_cents`. The offer is created with `status` `DRAFT`, `sent_at` null, and `version` 1. A draft offer does not occupy a slot. The creation of a `DRAFT` offer is the offer's initial state and is not itself a `ScholarshipOffer` state transition; consequently, creating a draft offer does not refresh the parent `Program`'s `updated_at` and does not increment the parent `Program`'s `version`. The program's `slots_projected` value (as reported by the utilization read endpoint described later in this section) is derived from the current set of `ScholarshipOffer` rows at read time, so the projected count visibly reflects the new draft on the very next read even though no field was written to the `Program` row at draft-creation time.

Dispatching a draft offer — the transition that moves `status` from `DRAFT` to `SENT` — is the slot-consuming event. The action requires three preconditions, evaluated in this order. First, the recipient athlete must already have `eligibility_status` equal to `CERTIFIED`; an attempt to send an offer to an uncertified or ineligible athlete is rejected with `ERR_ATHLETE_NOT_CERTIFIED`. Second, the issuing program must have at least one slot remaining: the boundary check is that one more than the program's current `slots_committed` must be no larger than its `scholarship_slot_cap`, which is equivalent to saying the current count must be strictly less than the cap. A program that is already at its cap rejects further sends with `ERR_SLOT_CAP_EXCEEDED`. Third, the program's `penalty_tier` must not be `POSTSEASON_BAN`; a program under postseason ban cannot send new offers (it is also the program whose existing `SENT` offers were forcibly retracted at the moment the ban was applied, as described in §3.7).

The request body for the send action also requires `expected_program_version` as a non-optional field, and the optimistic-concurrency-control rule from §2.5 applies: if the supplied value does not match the program's current `version`, the request is rejected with `ERR_STALE_PROGRAM_VERSION` (412). The acting coach must belong to the offer's program — that is, the coach's `X-User-ID` must match the `X-User-ID` that authored the offer — and a mismatch is rejected with `ERR_COACH_PROGRAM_MISMATCH`. On a successful send, the offer's `sent_at` is stamped with the current UTC instant from the system clock, the offer's `version` is incremented, and the issuing program's `slots_committed` is incremented by 1, its `updated_at` is refreshed, and its `version` is incremented.

A `SENT` offer has three possible resolutions, two by the athlete and one by the coach. The recipient — the athlete whose own `X-User-ID` matches the offer's `student_athlete_id` — may accept the offer, transitioning `status` from `SENT` to `ACCEPTED`; on acceptance, the athlete's `enrolled_program_id` is set to the offer's `program_id`, the athlete's `updated_at` and `version` are refreshed, and the offer's `version` is incremented. (Acceptance does not change `slots_committed`: an `ACCEPTED` offer continues to occupy the slot that the corresponding `SENT` offer was consuming.) The recipient may instead decline the offer, transitioning `status` from `SENT` to `DECLINED`; declination releases the slot — the program's `slots_committed` is decremented by 1, its `updated_at` is refreshed, and its `version` is incremented — and the offer's `version` is incremented. The coach who issued the offer may also withdraw it from the `SENT` state, transitioning `status` from `SENT` to `WITHDRAWN`; this withdrawal likewise decrements `slots_committed`, refreshes the program's `updated_at`, and increments the program's `version`, plus increments the offer's `version`. The coach may additionally withdraw an offer while it is still `DRAFT`, transitioning `status` from `DRAFT` to `WITHDRAWN`; this case applies no slot change because the draft was never committed, but it still increments the offer's `version`.

Two cascade-driven withdrawals are also possible and were described in their originating workflows. An eligibility denial for the offer's athlete (§3.2) drives a system-initiated transition from either `DRAFT → WITHDRAWN` or `SENT → WITHDRAWN`, where the `SENT` case decrements `slots_committed` and the `DRAFT` case does not. A booster-incident sustain that pushes the program to `POSTSEASON_BAN` (§3.7) drives a system-initiated transition from `SENT → WITHDRAWN` for every `SENT` offer on that program, each decrementing `slots_committed`. In every case — direct or cascade-driven — the offer's `version` is incremented exactly once per transition and its `updated_at` is refreshed.

The system tracks two distinct slot counts on each program, and a coach can request either through a single utilization read endpoint by supplying the `variant` query parameter. Both counts are integer counts and not subject to any rounding rule. The `base` variant — which is the default if `variant` is omitted — produces `slots_committed`: it counts every `ScholarshipOffer` whose `program_id` matches the program and whose `status` is either `SENT` or `ACCEPTED`. A `DRAFT` offer that has not yet been sent is not counted by the base variant, because only effective commitments occupy a slot under the cap. The `projected` variant produces `slots_projected`: it counts every `ScholarshipOffer` whose `program_id` matches the program and whose `status` is `DRAFT`, `SENT`, or `ACCEPTED`, excluding those whose recipient athlete already has at least one `EligibilityCertification` with `status` `DENIED`. The projected variant is forward-looking for coach pre-planning: it includes drafts but pre-removes athletes who are already disqualified. The two variants therefore differ exactly when the program has at least one `DRAFT` offer to an athlete whose certification is still `PENDING`; in that case the projected count is larger than the base count by the number of such drafts. The utilization read returns `program_id`, `variant`, `slot_count`, and `scholarship_slot_cap`. Whenever ties must be broken when iterating offers — for example to give cascade-driven side effects a deterministic order — the system uses the offer's own `created_at` ascending; the offer `id` never participates in tie-breaking.

List endpoints for offers are filterable by `program_id`, `student_athlete_id`, and `status`.

### 3.5. NIL Deal Lifecycle and Tier Classification

A `StudentAthlete` proposes a NIL endorsement deal by supplying their own `student_athlete_id` (which must equal `X-User-ID` for entity-backed ownership), the sponsor's `brand_name`, the `gross_value_cents` of the deal, and an optional `agent_fee_pct` expressed as a decimal fraction between 0.0 and 0.30 inclusive (defaulting to 0.0 when omitted). On creation the deal is placed in `status` `PROPOSED`, `review_round` is 0, and `version` is 1. The submitter does not need to be certified at the moment of proposal — only at the moment the deal is submitted for review.

At creation time, the system computes the deal's `net_value_cents` and assigns its `tier`. The computation is order-sensitive and the order is pinned: first, `net_value_cents` is the gross value multiplied by one minus `agent_fee_pct`, with the resulting cent value rounded to the nearest whole cent using banker's rounding (half-to-even). Only then is the resulting integer cent count compared against the tier cutoffs, and the comparison is one-sided so that the cutoffs are themselves the boundary points. If `net_value_cents` is strictly less than 60,000 cents (six hundred dollars), `tier` is `DE_MINIMIS`. Otherwise, if `net_value_cents` is strictly less than 500,000 cents (five thousand dollars), `tier` is `STANDARD`. Otherwise, `tier` is `HIGH_VALUE`. The boundary at exactly 60,000 cents and exactly 500,000 cents therefore falls into the higher tier — exactly 60,000 cents is `STANDARD`, exactly 500,000 cents is `HIGH_VALUE`. The order of operations matters at the boundary: a deal with `gross_value_cents` 60,000 and `agent_fee_pct` 0.10 yields `net_value_cents` 54,000 — `DE_MINIMIS`, not `STANDARD` — whereas a naive classification on the gross alone would place it in `STANDARD`. The same tier-classification rule is re-evaluated on every state transition of the deal, because the tier decides whether the approve precondition fires.

A `NILReviewer` carries the deal forward. Submitting for review transitions `status` from `PROPOSED` to `UNDER_REVIEW`; the precondition is that the deal's athlete has `eligibility_status` equal to `CERTIFIED`, with a violation rejected as `ERR_ATHLETE_NOT_CERTIFIED`. The submitter's `X-User-ID` is recorded against the deal for the segregation-of-duties check at approval time. From `UNDER_REVIEW`, the reviewer has three terminal-or-cyclic options. The reviewer may request a revision, transitioning `status` from `UNDER_REVIEW` back to `PROPOSED`; this side path increments `review_round` by 1 and increments the deal's `version`, but is permitted only if the resulting `review_round` after the increment would be no larger than 3 — the system caps the number of revision cycles at three. A request beyond this cap is rejected as a state-violation (`ERR_INVALID_STATE`). The reviewer may reject the deal, transitioning `status` from `UNDER_REVIEW` to `REJECTED`; this requires `rejection_reason` to be supplied in the request body, drawn from `BRAND_PROHIBITED`, `ATHLETE_INELIGIBLE`, or `EXCEEDS_PROGRAM_LIMIT`. The reviewer may approve the deal, transitioning `status` from `UNDER_REVIEW` to `APPROVED`, subject to two preconditions evaluated in order.

The first precondition on approval is segregation of duties: the approver's `X-User-ID` must differ from the `X-User-ID` of every prior submitter and revision-requester of this same deal, across all revision cycles. A violation is rejected with `ERR_SOD_VIOLATION`. The second precondition is the high-value-under-sanction gate: if the deal's `tier` is `HIGH_VALUE` and the deal's athlete is enrolled in a program (i.e. `enrolled_program_id` is non-null) whose `penalty_tier` is anything other than `NONE`, approval is blocked. A violation is rejected with `ERR_PROGRAM_UNDER_SANCTION`. Equivalently: a high-value deal can be approved only when the athlete's enrolled program is under no sanction, while a `DE_MINIMIS` or `STANDARD` deal may be approved regardless of the program's `penalty_tier`. Every state transition on the deal increments its `version` by 1.

NIL deal list endpoints are filterable by `student_athlete_id`, `status`, and `tier`.

### 3.6. The Transfer Portal Window

Entering the transfer portal is the athlete's prerogative. A `StudentAthlete` (whose own `X-User-ID` equals the supplied `student_athlete_id`) creates a `TransferPortalEntry` by supplying their `student_athlete_id` and a `source_program_id` indicating the program they are leaving. On entry, the system stamps `entered_at` from the current UTC clock and computes `window_closes_at` as `entered_at` plus exactly 45 days, with no clamping or alignment to any boundary; the entry is created with `status` `ENTERED` and `version` 1, and the athlete's `in_transfer_portal` flag is set to `true` (refreshing the athlete's `updated_at` and incrementing the athlete's `version`). `matched_program_id` is null at this point.

While an entry remains in `ENTERED` status, three transitions are available, and each is gated by the half-open transfer-portal window. The window is open while the current UTC instant is strictly less than `window_closes_at`; the boundary at exactly `entered_at` plus 45 days is the moment the window closes, and operations attempted at or after that boundary are rejected as `ERR_PORTAL_WINDOW_CLOSED`.

A `ComplianceOfficer` matches the entry to a destination program through a transition that moves `status` from `ENTERED` to `MATCHED`. The request requires `matched_program_id` and `expected_transferportalentry_version`. The preconditions, evaluated in the standard order: the match must occur while the window is still open (`current_utc` is strictly less than `window_closes_at`); the athlete's `eligibility_status` must be `CERTIFIED`; the destination program identified by `matched_program_id` must have a slot available, in the same boundary sense as a scholarship-offer send (one more than the destination's `slots_committed` must be no larger than its `scholarship_slot_cap`); and the supplied `expected_transferportalentry_version` must match the entry's current `version` (with a mismatch rejected as `ERR_STALE_ENTRY_VERSION`, 412). On a successful match the entry's `matched_program_id` is set to the supplied program, the athlete's `enrolled_program_id` is set to that same program, the athlete's `in_transfer_portal` flag is flipped back to `false` (refreshing `updated_at` and incrementing the athlete's `version`), and the entry's `version` is incremented.

The same athlete who entered may withdraw their entry, transitioning `status` from `ENTERED` to `WITHDRAWN`; this is permitted only while the window is open and rejected with `ERR_PORTAL_WINDOW_CLOSED` once the window has closed. On withdrawal the athlete's `in_transfer_portal` is flipped to `false` (refreshing `updated_at` and incrementing the athlete's `version`), and the entry's `version` is incremented.

Finally, the system itself drives the third transition through the clock-driven sweep capability introduced in §2.8. When the sweep runs and the current clock has crossed an entry's `window_closes_at`, that entry transitions from `ENTERED` to `EXPIRED`; the athlete's `in_transfer_portal` is flipped to `false` (with the customary `updated_at` and `version` bump), and the entry's `version` is incremented. The sweep is idempotent: a second run with no new clock movement will find nothing to expire and will return an empty `expired_entry_ids` list with `expired_count` 0. Transfer-portal list endpoints are filterable by `student_athlete_id`, `status`, `source_program_id`, and `matched_program_id`.

### 3.7. Booster Incidents and the Program Penalty Ladder

The booster-incident workflow is the system's mechanism for assessing penalties against programs whose boosters provide impermissible benefits to athletes. A `ComplianceOfficer` reports an incident by supplying the implicated `program_id`, the `booster_name` (a free-text identifier), the involved `student_athlete_id`, and the `alleged_value_cents` of the improper benefit. The supplied `alleged_value_cents` must be strictly greater than zero — a report with `alleged_value_cents` equal to 0 is rejected with `ERR_ZERO_VALUE_INCIDENT`, because a zero-value allegation carries no investigatory weight. On creation the incident's `status` is `REPORTED`, `severity_weight` is 0, and `version` is 1.

A reported incident is opened for investigation by a `ComplianceOfficer`, transitioning `status` from `REPORTED` to `INVESTIGATING`; this transition carries no additional preconditions beyond the standard authorization and state checks, and it increments the incident's `version`. From the `INVESTIGATING` state, the officer has two terminal options. Dismissal transitions `status` from `INVESTIGATING` to `DISMISSED` and increments the incident's `version`; no further effects occur, and the dismissed incident contributes nothing to the program's penalty score.

Sustaining the incident transitions `status` from `INVESTIGATING` to `SUSTAINED` and is the action that drives the multi-link cascade through the program penalty ladder. The action requires `expected_boosterincident_version` in the request body, and a mismatch with the incident's current `version` is rejected with `ERR_STALE_INCIDENT_VERSION` (412). On a successful sustain, the system first stamps `severity_weight` onto the incident by classifying the incident's `alleged_value_cents` into one of four tiers. An incident whose `alleged_value_cents` is strictly less than 50,000 (five hundred dollars) receives `severity_weight` 1; one whose value is at least 50,000 but strictly less than 500,000 (five thousand dollars) receives 3; one whose value is at least 500,000 but strictly less than 2,500,000 (twenty-five thousand dollars) receives 7; and one whose value is at least 2,500,000 receives 15. The boundary at each cutoff value falls into the higher tier — exactly 50,000 cents receives weight 3, exactly 500,000 cents receives weight 7, exactly 2,500,000 cents receives weight 15. The incident's `version` is incremented.

The system then recomputes the program's `penalty_tier` by summing the `severity_weight` of every `BoosterIncident` for that `program_id` whose `status` is `SUSTAINED` (which now includes the one just sustained) — incidents in any other status, including `DISMISSED`, contribute nothing. If the total weight is exactly 0, the program's `penalty_tier` is `NONE`. Otherwise, if the total is strictly less than 5, the tier is `LEVEL_I`. Otherwise, if the total is strictly less than 15, the tier is `LEVEL_II`. Otherwise (a total of 15 or more), the tier is `POSTSEASON_BAN`. The boundaries at 5 and 15 fall into the higher tier. The program's `penalty_tier` field is updated to the newly computed value, the program's `updated_at` is refreshed, and the program's `version` is incremented. When tie-breaking is required while iterating sustained incidents, the system uses each incident's `created_at` ascending and never the incident `id`.

If the recomputed `penalty_tier` is `POSTSEASON_BAN`, the system extends the cascade one further link: every `ScholarshipOffer` for that `program_id` whose `status` is currently `SENT` is auto-transitioned to `WITHDRAWN` by the system. Each such cascade-withdrawal decrements the program's `slots_committed` by 1 (refreshing `updated_at` and incrementing the program's `version` on each), refreshes the offer's `updated_at`, and increments the offer's `version`. A program in `POSTSEASON_BAN` is also forbidden from sending any new offer, as described in §3.4. `DRAFT` offers are not cascade-withdrawn by the sustain — only `SENT` offers, because only `SENT` offers occupy a slot that needs to be released. Whether or not the postseason-ban cascade fires, the recompute itself always runs.

A program may also fall out of `POSTSEASON_BAN` over time: if the population of sustained incidents shifts (for example, through the addition of new sustained incidents on a different program, or through any data action that legitimately changes the sustained-incident set), the recompute uses whatever sustained set obtains at the moment it runs, and the resulting `penalty_tier` is whatever the boundary rules above produce on that set.

Booster-incident list endpoints are filterable by `program_id`, `student_athlete_id`, and `status`.

## 4. Endpoint Definitions

Operations that create new stand-alone resources (e.g. a new `Program`, `Period`, `StudentAthlete`, `EligibilityCertification`, `RecruitingContact`, `ScholarshipOffer`, `NILDeal`, `TransferPortalEntry`, or `BoosterIncident`) return `201 Created`. Operations that modify an existing resource — including every state-machine action endpoint — return `200 OK`. The summary table below lists method, path, and authorized roles only; request bodies, response bodies, and side effects are described in §3 narratives and §2 cross-cutting principles.

| Method | Path                                                    | Description                                                      | Authorized Role(s)                                                            |
| ------ | ------------------------------------------------------- | ---------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| POST   | `/ncaa/programs`                                        | Create a Program                                                 | ComplianceOfficer                                                             |
| GET    | `/ncaa/programs/{id}`                                   | Read a single Program                                            | ComplianceOfficer, Coach, NILReviewer, EligibilityCenter, StudentAthlete      |
| GET    | `/ncaa/programs`                                        | List Programs                                                    | ComplianceOfficer, Coach, NILReviewer, EligibilityCenter, StudentAthlete      |
| GET    | `/ncaa/programs/{id}/utilization`                       | Read a Program's slot utilization (base or projected variant)    | ComplianceOfficer, Coach                                                      |
| POST   | `/ncaa/programs/{id}/periods`                           | Create a recruiting-calendar Period for the Program              | ComplianceOfficer                                                             |
| GET    | `/ncaa/programs/{id}/periods`                           | List Periods for a Program                                       | ComplianceOfficer, Coach                                                      |
| GET    | `/ncaa/periods/{id}`                                    | Read a single Period                                             | ComplianceOfficer, Coach                                                      |
| POST   | `/ncaa/student-athletes`                                | Create a StudentAthlete (intake)                                 | ComplianceOfficer                                                             |
| GET    | `/ncaa/student-athletes/{id}`                           | Read a single StudentAthlete                                     | ComplianceOfficer, Coach, NILReviewer, EligibilityCenter, StudentAthlete      |
| GET    | `/ncaa/student-athletes`                                | List StudentAthletes                                             | ComplianceOfficer, Coach, NILReviewer, EligibilityCenter                      |
| POST   | `/ncaa/eligibility-certifications`                      | Submit an Eligibility Center review (snapshots current values)   | EligibilityCenter                                                             |
| GET    | `/ncaa/eligibility-certifications/{id}`                 | Read a single EligibilityCertification                           | EligibilityCenter, ComplianceOfficer                                          |
| GET    | `/ncaa/eligibility-certifications`                      | List EligibilityCertifications                                   | EligibilityCenter, ComplianceOfficer                                          |
| POST   | `/ncaa/eligibility-certifications/{id}/approve`         | Approve a pending certification                                  | EligibilityCenter                                                             |
| POST   | `/ncaa/eligibility-certifications/{id}/deny`            | Deny a pending certification (cascades scholarship withdrawals)  | EligibilityCenter                                                             |
| POST   | `/ncaa/recruiting-contacts`                             | Log a recruiting contact                                         | Coach                                                                         |
| GET    | `/ncaa/recruiting-contacts/{id}`                        | Read a single RecruitingContact                                  | ComplianceOfficer, Coach                                                      |
| GET    | `/ncaa/recruiting-contacts`                             | List RecruitingContacts                                          | ComplianceOfficer, Coach                                                      |
| POST   | `/ncaa/scholarship-offers`                              | Create a ScholarshipOffer in DRAFT                               | Coach                                                                         |
| GET    | `/ncaa/scholarship-offers/{id}`                         | Read a single ScholarshipOffer                                   | ComplianceOfficer, Coach, StudentAthlete                                      |
| GET    | `/ncaa/scholarship-offers`                              | List ScholarshipOffers                                           | ComplianceOfficer, Coach, StudentAthlete                                      |
| POST   | `/ncaa/scholarship-offers/{id}/send`                    | Send a DRAFT offer (slot capacity enforced; OCC on Program)      | Coach                                                                         |
| POST   | `/ncaa/scholarship-offers/{id}/accept`                  | Athlete accepts a SENT offer                                     | StudentAthlete                                                                |
| POST   | `/ncaa/scholarship-offers/{id}/decline`                 | Athlete declines a SENT offer (releases the slot)                | StudentAthlete                                                                |
| POST   | `/ncaa/scholarship-offers/{id}/withdraw`                | Coach withdraws a DRAFT or SENT offer                            | Coach                                                                         |
| POST   | `/ncaa/nil-deals`                                       | Create a NILDeal in PROPOSED (net and tier computed)             | StudentAthlete                                                                |
| GET    | `/ncaa/nil-deals/{id}`                                  | Read a single NILDeal                                            | NILReviewer, ComplianceOfficer, StudentAthlete                                |
| GET    | `/ncaa/nil-deals`                                       | List NILDeals                                                    | NILReviewer, ComplianceOfficer, StudentAthlete                                |
| POST   | `/ncaa/nil-deals/{id}/submit-for-review`                | Move PROPOSED → UNDER_REVIEW                                     | NILReviewer                                                                   |
| POST   | `/ncaa/nil-deals/{id}/request-revision`                 | Cycle UNDER_REVIEW → PROPOSED with revision-count bump           | NILReviewer                                                                   |
| POST   | `/ncaa/nil-deals/{id}/approve`                          | Approve UNDER_REVIEW → APPROVED (segregation of duties enforced) | NILReviewer                                                                   |
| POST   | `/ncaa/nil-deals/{id}/reject`                           | Reject UNDER_REVIEW → REJECTED                                   | NILReviewer                                                                   |
| POST   | `/ncaa/transfer-portal-entries`                         | Enter the Transfer Portal                                        | StudentAthlete                                                                |
| GET    | `/ncaa/transfer-portal-entries/{id}`                    | Read a single TransferPortalEntry                                | ComplianceOfficer, StudentAthlete                                             |
| GET    | `/ncaa/transfer-portal-entries`                         | List TransferPortalEntries                                       | ComplianceOfficer, StudentAthlete                                             |
| POST   | `/ncaa/transfer-portal-entries/{id}/match`              | Match an entry to a destination program (OCC on the entry)       | ComplianceOfficer                                                             |
| POST   | `/ncaa/transfer-portal-entries/{id}/withdraw`           | Athlete withdraws from the portal (window-open only)             | StudentAthlete                                                                |
| POST   | `/ncaa/booster-incidents`                               | Report a Booster violation                                       | ComplianceOfficer                                                             |
| GET    | `/ncaa/booster-incidents/{id}`                          | Read a single BoosterIncident                                    | ComplianceOfficer                                                             |
| GET    | `/ncaa/booster-incidents`                               | List BoosterIncidents                                            | ComplianceOfficer                                                             |
| POST   | `/ncaa/booster-incidents/{id}/open-investigation`       | REPORTED → INVESTIGATING                                         | ComplianceOfficer                                                             |
| POST   | `/ncaa/booster-incidents/{id}/sustain`                  | INVESTIGATING → SUSTAINED (recomputes penalty tier; cascades)    | ComplianceOfficer                                                             |
| POST   | `/ncaa/booster-incidents/{id}/dismiss`                  | INVESTIGATING → DISMISSED                                        | ComplianceOfficer                                                             |
| POST   | `/ncaa/_clock/set_current_utc`                          | Set the system clock (test-driving)                              | ComplianceOfficer                                                             |
| POST   | `/ncaa/_jobs/sweep-portal-expirations`                  | Idempotent sweep of transfer-portal expirations                  | ComplianceOfficer                                                             |

## 5. Error Code Catalogue

| Error ID                          | HTTP Status Code         |
| --------------------------------- | ------------------------ |
| `ERR_UNAUTHENTICATED`             | 401 Unauthorized         |
| `ERR_UNAUTHORIZED`                | 403 Forbidden            |
| `ERR_NOT_FOUND`                   | 404 Not Found            |
| `ERR_INVALID_REQUEST`             | 400 Bad Request          |
| `ERR_INVALID_STATE`               | 409 Conflict             |
| `ERR_STALE_PROGRAM_VERSION`       | 412 Precondition Failed  |
| `ERR_STALE_ENTRY_VERSION`         | 412 Precondition Failed  |
| `ERR_STALE_INCIDENT_VERSION`      | 412 Precondition Failed  |
| `ERR_DEAD_PERIOD_CONTACT`         | 422 Unprocessable Entity |
| `ERR_QUIET_PERIOD_VIOLATION`      | 422 Unprocessable Entity |
| `ERR_OUTSIDE_RECRUITING_WINDOW`   | 422 Unprocessable Entity |
| `ERR_PERIOD_OVERLAP`              | 422 Unprocessable Entity |
| `ERR_PORTAL_WINDOW_CLOSED`        | 422 Unprocessable Entity |
| `ERR_COACH_PROGRAM_MISMATCH`      | 403 Forbidden            |
| `ERR_SOD_VIOLATION`               | 403 Forbidden            |
| `ERR_ATHLETE_NOT_CERTIFIED`       | 422 Unprocessable Entity |
| `ERR_PROGRAM_UNDER_SANCTION`      | 422 Unprocessable Entity |
| `ERR_SLOT_CAP_EXCEEDED`           | 422 Unprocessable Entity |
| `ERR_ZERO_VALUE_INCIDENT`         | 422 Unprocessable Entity |
| `ERR_INVALID_INTERVAL`            | 422 Unprocessable Entity |
