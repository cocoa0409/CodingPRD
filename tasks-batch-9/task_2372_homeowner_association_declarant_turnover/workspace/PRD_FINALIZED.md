# HOA Declarant Turnover API — Product Requirements Document

## 1. Introduction

When a residential community is built out, control of the homeowner association does not simply change hands on a chosen morning. The declaration that created the community fixes a trigger — a percentage of lots sold, or an outside calendar date — and once that trigger fires a long, adversarial, statute-driven handover begins. The developer (the *declarant*) must open its books, deliver records, warranties, plans, permits and vendor contracts, finish or answer for amenities it promised, hand over deeds to the common areas, and stop writing the monthly cheque that has been quietly covering the association's operating deficit. The owners, acting through a transition committee, must audit what they are receiving, reserve for construction defects before the statute of repose runs, elect their own board, decide which developer-affiliated service contracts to keep, and re-forecast a budget that no longer enjoys a subsidy.

This API is the system of record for that handover. It tracks a single `TurnoverCase` per association along two dimensions that move on independent triggers — a governance dimension that converts a declarant-appointed board into an owner-elected one, and a financial dimension that runs from an active subsidy through a transition audit to final settlement — and it derives a single posture from the pair that determines whether the community's books are still open for business. Around that case sit the artefacts the transition consumes: platted lots and their sale closings, common area components and their construction and conveyance milestones, reserve studies and their adequacy verdicts, a declarant subsidy ledger with reversible entries, transition audit engagements, construction defect claims with tiered reserves, vendor contracts with assignment-consent rights, records transfer items, board seats, and assessment schedules.

Two design commitments run through everything that follows. First, **segregation of duties is enforced by user identity, not by role labels alone**: the auditor who signs a report may not be the person who posted the money inside the audited window, and the committee member who certified the turnover trigger may not then seat a director. Second, **every derived number is deterministic and every deadline is measured against a server-controlled logical clock**, so that a repose deadline, a cancellation window, or a fixed turnover date produces the same verdict on every replay. The entire business surface is mounted under `/hoa`, with one auxiliary test-driving mount for the clock.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts, formats, and cross-cutting rules that apply to every request the API serves.

### 2.1. User and Role-Based Access Control

Every request must identify its caller through two mandatory HTTP headers: `X-User-ID`, carrying the acting user's identifier, and `X-User-Role`, carrying the capacity in which that user is acting. The API recognises exactly five roles: `PlatformAdmin`, `Declarant`, `TransitionCommittee`, `Auditor`, and `ElectionInspector`. If either header is absent, or if `X-User-Role` is not one of those five spellings, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request is considered. When the headers are well formed but the role is not entitled to the operation, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `TransitionCommittee`, `X-User-ID` is the `id` of the acting `Association`; ownership checks on any resource that references an `Association` compare the resource's `association_id` foreign-key field to `X-User-ID`, and a committee acting on another community's lot, component, claim, contract, study, schedule, records item, director or turnover case is refused with `ERR_ROLE_NOT_PERMITTED`. For a resource that references the association indirectly — a `RecordsTransferItem` or a `Director`, which carry `turnover_case_id` rather than `association_id` — the comparison is made against the `association_id` of the owning turnover case. When `X-User-Role` is `PlatformAdmin`, `Declarant`, `Auditor`, or `ElectionInspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a transition writes it — as `posted_by_user_id` on a `SubsidyEntry`, `issued_by_user_id` on an `AuditEngagement`, `seated_by_user_id` on a `Director`, and `trigger_certified_by_user_id` on a `TurnoverCase` — but never compares it to any entity's `id`.

Responsibilities are deliberately disjoint. `PlatformAdmin` is the registry operator: it registers associations, opens turnover cases, and owns the logical clock. `Declarant` is the developer and its affiliates: lot records and sale closings, component registration and construction milestones, deed tender, records delivery, the subsidy ledger and its reversals, vendor procurement, declarant-appointed seats, and the developer's side of claim negotiation. `TransitionCommittee` is the owner side: trigger certification, dimension advances, conveyance acceptance, records review, reserve studies, defect claims and their owner-side actions, the repose sweep, vendor consent and cancellation, and budget re-forecasting and adoption. `Auditor` engages over an accounting period and issues the report. `ElectionInspector` seats and rescinds owner-elected directors. Every read operation under the business mount is available to all five roles.

Five endpoints are shared dispatchers on which the **discriminator in the payload decides which role may act**, and that check runs before any state check, so a role mismatch outranks an illegal-from-state rejection:

- Component milestones: `BUILD_COMPLETE` and `DEED_TENDERED` are `Declarant`-only; `CONVEYANCE_ACCEPTED` is `TransitionCommittee`-only.
- Records item transitions: `DELIVER` is `Declarant`-only; `ACCEPT` and `REJECT` are `TransitionCommittee`-only.
- Vendor contract actions: `REQUEST_ASSIGNMENT` is `Declarant`-only; `CONSENT`, `REFUSE_CONSENT` and `CANCEL` are `TransitionCommittee`-only.
- Defect claim actions: `REJECT` and `ACCEPT` are `Declarant`-only; `NOTICE`, `REINVESTIGATE`, `RESERVE` and `WITHDRAW` are `TransitionCommittee`-only.
- Director seating: a `seat_type` of `DECLARANT_APPOINTED` is `Declarant`-only; `OWNER_ELECTED` is `ElectionInspector`-only.

Beyond role entitlement, two independent certifications carry an identity-based segregation-of-duties rule, both rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). An `Auditor` may not issue a report on an engagement when its own `X-User-ID` equals the `posted_by_user_id` of any `POSTED` `SubsidyEntry` of that association whose `period_month` falls inside the engagement's window — an auditor who posted money *outside* the window is untainted and may still issue. And whoever seats a director must not be the user recorded in the case's `trigger_certified_by_user_id`.

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

List endpoints accept two query parameters. `limit` caps the number of records returned; it defaults to 10 when omitted, may not be smaller than 1, and may not exceed 100. `offset` is the number of records to skip and defaults to 0. Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending, which is also the processing order every cascade in this specification uses when it touches a set of sibling rows. Because `created_at` is real-time and carries only millisecond precision, two rows can share a value; rows that tie keep the order in which they were created, so the effective ordering is always creation order.

List responses report `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the filtered set before the window is applied and `has_more` indicates whether records remain beyond it.

### 2.4. Record Identity, Versioning and Path Resolution

Every resource the API persists — associations, turnover cases, lots, common area components, reserve studies, subsidy entries, audit engagements, defect claims, vendor contracts, records transfer items, directors and assessment schedules — carries the same four system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the record first came into existence, taken from the host's real time rather than from the logical clock of §2.5. `updated_at` is an ISO 8601 UTC timestamp in the same format drawn from that same real-time source, refreshed on every mutation of the record, including mutations the server performs on its own initiative as a cascade of some other request. `version` is an integer that starts at 1 on creation and increments by one on every mutation. No resource in this system omits `updated_at` or `version`.

Recomputation of a derived field counts as a mutation. When the close of a lot sale moves an association's `sold_lot_count`, when a claim reserve moves its `reserve_claim_committed_cents`, or when a cascade flips its `budget_forecast_status`, the association's `updated_at` is refreshed and its `version` advances — which is exactly why the concurrency rule in §2.10 exists.

Identifiers in a request path are resolved strictly left to right, and the first one that fails to resolve determines the error. Each entity has its own not-found code: `ERR_ASSOCIATION_NOT_FOUND`, `ERR_TURNOVER_CASE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_COMPONENT_NOT_FOUND`, `ERR_RESERVE_STUDY_NOT_FOUND`, `ERR_SUBSIDY_ENTRY_NOT_FOUND`, `ERR_AUDIT_ENGAGEMENT_NOT_FOUND`, `ERR_DEFECT_CLAIM_NOT_FOUND`, `ERR_VENDOR_CONTRACT_NOT_FOUND`, `ERR_RECORDS_ITEM_NOT_FOUND`, `ERR_DIRECTOR_NOT_FOUND` and `ERR_ASSESSMENT_SCHEDULE_NOT_FOUND`, each returned with HTTP 404. Foreign keys supplied in a request body are resolved with the same codes, and two of them must additionally agree with their sibling: a defect claim's `component_id` and a vendor contract's `component_id` must each name a component belonging to the same `association_id` the body supplies. A component that exists but belongs to a different association is reported as `ERR_COMPONENT_NOT_FOUND`, not as a permission problem.

### 2.5. The Logical Clock and Statutory Deadlines

No business instant in this system is read from the host's wall clock. Every business "now" — the instant stamped into `trigger_certified_at`, `conveyed_at`, `delivered_at` and `vacated_at`, and every comparison against a `repose_deadline`, a `cancellation_window_end`, or an association's `fixed_turnover_date` — is taken from a server-held logical clock. Before any call is made to set it, that clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. A `PlatformAdmin` may move it by supplying a `to_iso8601` instant; the response reports the new value as `current_utc`. Moving the clock performs no business transition, supersedes nothing, and touches no record. The system-managed audit stamps of §2.4, `created_at` and `updated_at`, stand outside this rule: they are written from the host's real time at the moment the record is created or mutated, and the logical clock neither supplies nor influences them. The envelope's `api_request_timestamp` is likewise real time.

Deadline comparisons in this specification are stated with their inclusivity, and the inclusivity matters. Serving notice of a defect claim is permitted while the clock is at or before the claim's `repose_deadline`; the repose sweep only bars a claim once the clock is strictly past it. Cancelling a developer-affiliated contract is permitted while the clock is at or before `cancellation_window_end`. Certifying a fixed-date turnover trigger is permitted once the clock is at or after `fixed_turnover_date`.

### 2.6. Cents, Percentages and Rounding Discipline

Monetary amounts are integers denominated in cents; a field name ending in `_cents` never carries a fractional part in a request or a response. Percentages are numbers carried to exactly two decimal places, and unless a rule says otherwise they are produced by rounding half up — a value whose third decimal digit is 5 rounds away from zero. This applies to `sold_lot_pct`, `percent_funded`, `records_transfer_completeness_pct` and `increase_pct_vs_prior`. Threshold comparisons are made against the **rounded** value, never against the unrounded quotient, so a two-of-three sold ratio is compared as 66.67 rather than as an endlessly repeating decimal.

Where a money calculation needs a directional rounding rather than half-up, this document says so explicitly at the point of use, and the direction is part of the contract: the per-component fully funded share is floored, each projected annual expenditure in the cash-flow walk is floored, the recommended reserve contribution is a ceiling, and the per-lot monthly assessment is a ceiling. Litigation administrative fees are the one money value rounded half up to whole cents. Ordering matters as much as direction: where this document pins the sequence of a calculation — select the fee tier from the subtotal before adding the fee, divide to a per-lot figure before multiplying back up to an annual total — that sequence is normative, and rearranging it into an algebraically "equivalent" form produces a different, wrong answer.

### 2.7. Rejection Precedence: The Order in Which a Request Is Judged

A single request can violate several rules at once, and clients depend on getting the same code every time. The server therefore evaluates a fixed ladder and returns on the first failure:

1. **Authentication.** Both headers present and `X-User-Role` among the five declared roles, else `ERR_UNAUTHENTICATED` (401).
2. **Role entitlement.** The acting role may invoke this operation; a `TransitionCommittee` caller's `X-User-ID` matches the association the target resource belongs to; and on each of the five shared dispatchers described in §2.1 the requested discriminator belongs to the acting role. Failure is `ERR_ROLE_NOT_PERMITTED` (403). This runs *before* any state check, so a wrong-role request against a resource that is also in the wrong state reports the role problem.
3. **Segregation of duties.** The two identity comparisons of §2.1 — audit issuance against in-window subsidy posters, director seating against the trigger certifier — reported as `ERR_SEGREGATION_OF_DUTIES` (403).
4. **Path existence.** Every identifier in the path resolves, left to right, else the matching 404 code.
5. **Body reference existence.** Every foreign key in the body resolves and cross-entity bodies agree, else the matching 404 code.
6. **Request shape.** Required fields present, enum members legal, numbers inside their declared ranges, `period_month` matching a four-digit year, a hyphen and a two-digit month in the range 01 through 12, `period_end` at or after `period_start`, `service_window_end` strictly after `service_window_start`, and action-conditional fields present — `effective_date` for `BUILD_COMPLETE`, `valuation_basis` for `RESERVE`, `settlement_amount_cents` for `ACCEPT`, `rejection_reason` for `REJECT`, `method` for `RECOMPUTE`, and `subsidy_end_date` when the financial dimension is advanced out of `SUBSIDY_ACTIVE`. Failure is `ERR_INVALID_REQUEST` (400). Computed and system-owned fields that a client supplies anyway are silently ignored rather than rejected.
7. **Association version match.** Where an operation carries `expected_association_version`, it must equal the association's current `version`, else `ERR_STALE_ASSOCIATION_VERSION` (412). See §2.10.
8. **Settlement lock.** The association's turnover case, where one exists, must not be in the `SETTLED_LOCKED` posture, else `ERR_TURNOVER_SETTLED_LOCKED` (409). See §2.8.
9. **State legality.** The target must be in a state from which the requested transition is defined — which also covers the one-case-per-association rule (`ERR_TURNOVER_CASE_EXISTS`), adoption of a study whose adequacy has never been evaluated (`ERR_ADEQUACY_NOT_EVALUATED`), and a subsidy entry being reversed at most once (`ERR_SUBSIDY_ENTRY_ALREADY_REVERSED`). The family is `ERR_TURNOVER_STAGE_INVALID`, `ERR_LOT_STATE_INVALID`, `ERR_COMPONENT_MILESTONE_INVALID`, `ERR_CLAIM_STATE_INVALID`, `ERR_CONTRACT_STATE_INVALID`, `ERR_RECORDS_ITEM_STATE_INVALID`, `ERR_DIRECTOR_STATE_INVALID`, `ERR_AUDIT_NOT_ISSUABLE`, `ERR_NOT_IN_DRAFT`, `ERR_ADEQUACY_NOT_EVALUATED`, `ERR_SUBSIDY_ENTRY_ALREADY_REVERSED` and `ERR_TURNOVER_CASE_EXISTS`, all HTTP 409.
10. **Cross-entity state preconditions** (HTTP 409). Serving notice requires the claim's component to have been conveyed (`ERR_COMPONENT_NOT_CONVEYED`); creating an assessment schedule requires the case's financial dimension to have left `SUBSIDY_ACTIVE` (`ERR_SUBSIDY_STILL_ACTIVE`) and an adopted reserve study to exist (`ERR_RESERVE_STUDY_NOT_ADOPTED`); advancing the financial dimension out of `SUBSIDY_ACTIVE` requires an audit engagement in `ENGAGED` or `ISSUED` (`ERR_TRANSITION_AUDIT_MISSING`).
11. **Statutory clocks** (HTTP 422). Notice against `repose_deadline` (`ERR_REPOSE_PERIOD_EXPIRED`) and cancellation against `cancellation_window_end` (`ERR_CANCELLATION_WINDOW_CLOSED`).
12. **Occupancy and uniqueness** (HTTP 409). Audit period overlap (`ERR_AUDIT_PERIOD_OVERLAP`), vendor service window collision (`ERR_SERVICE_WINDOW_CONFLICT`), and duplicate `lot_number` within an association (`ERR_DUPLICATE_LOT_NUMBER`).
13. **Open declarant obligations** (HTTP 422), evaluated only on a dimension advance: an unresolved developer-affiliated cancellable contract (`ERR_ASSIGNMENT_CONSENT_REQUIRED`), an overdue unbuilt amenity (`ERR_UNBUILT_AMENITY_OUTSTANDING`), and records completeness below the gate for the requested advance (`ERR_RECORDS_INCOMPLETE`).
14. **Statutory thresholds and caps** (HTTP 422): `ERR_TURNOVER_THRESHOLD_NOT_MET`, `ERR_FIXED_TURNOVER_DATE_NOT_REACHED`, `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`, `ERR_SEAT_CAPACITY_EXCEEDED` and `ERR_OWNER_VOTE_REQUIRED`.
15. **Money last** (HTTP 422): a claim reserve must fit inside the association's available claim pool (`ERR_CLAIM_RESERVE_INSUFFICIENT`), and settlement requires an issued clean audit with no standing block (`ERR_SETTLEMENT_BLOCKED`).

### 2.8. The Turnover Posture Gate

A turnover case exposes both of its dimensions and also a derived third field, `turnover_posture`, which projects the pair onto a single posture. The branches are evaluated top to bottom and the first match wins: the posture is `DECLARANT_CONTROL_OPEN` when `governance_status` is `DECLARANT_CONTROL` and `financial_status` is `SUBSIDY_ACTIVE`; otherwise `SETTLED_LOCKED` when `governance_status` is `OWNER_CONTROL` and `financial_status` is `SETTLED`; otherwise `OWNER_CONTROL_OPEN` when `governance_status` is `OWNER_CONTROL`; otherwise `TRANSITION_RESTRICTED`. It is re-derived at the end of every transition that changes either dimension, and it is never set directly by a client.

`SETTLED_LOCKED` is a gate rather than a label. While the association's case stands in that posture, fifteen operations are refused with `ERR_TURNOVER_SETTLED_LOCKED`: closing a lot sale; accepting conveyance of a component; opening a defect claim; every defect claim action; posting a subsidy entry; reversing a subsidy entry; registering a vendor contract; every vendor contract action; opening a reserve study; every reserve study action; creating an assessment schedule; adopting an assessment schedule; certifying the turnover trigger; advancing either dimension; and seating a director. The complementary set is equally deliberate and is *not* gated: registering lots, components and records items, recording the `BUILD_COMPLETE` and `DEED_TENDERED` milestones, driving records items through their review cycle, engaging and issuing an audit, rescinding a director, sweeping for expired repose periods, and the two registry operations that create associations and turnover cases. An association that has no turnover case at all is never gated by this rule.

### 2.9. Forecast Staleness and Cascade Discipline

An association carries a `budget_forecast_status` of either `CURRENT` or `STALE`, and it is the hinge of most of the system's cascades. It starts at `CURRENT`. Any event that changes what the operating budget must fund — certification of the turnover trigger, the end of the declarant subsidy, refusal of assignment consent on a vendor contract, or cancellation of a developer-affiliated contract — sets it to `STALE` and advances the association's `version`. Adoption of an assessment schedule is the only event that returns it to `CURRENT`.

Whenever the forecast goes stale, every `DRAFT` assessment schedule of that association is superseded, because a draft built on the old obligations is no longer a candidate for adoption. Cascades are transitive: a hop can be caused by a preceding hop rather than by the original request, and the reader should expect a single request to walk several levels deep. Whenever a hop touches a set of sibling rows — resigning appointed directors, moving contracts into a cancellable posture, superseding drafts, accepting delivered records items, recomputing repose deadlines, barring time-expired claims — those rows are processed in `created_at` ascending order, and each row touched is a mutation of its own record with its own `updated_at` refresh and `version` increment.

### 2.10. Optimistic Concurrency on the Association Record

Creating an assessment schedule is the one write in this system that requires the client to prove it has seen the association's current state. The creation payload must carry `expected_association_version` — a required field, not an optional one — holding the `version` the client last observed on the `Association`. If that value does not equal the association's current `version`, the request is rejected with `ERR_STALE_ASSOCIATION_VERSION` and HTTP 412, and nothing is created.

The reason is that a second schedule creation is a perfectly legal product operation: a new draft supersedes the association's prior draft by design. Without a version check, a client working from a stale reading of the reserve recommendation, the subsidy end date, the billable lot set or the forecast status would silently discard a draft built on newer data and replace it with an obsolete forecast. The check is the only signal that its view has moved on. No other endpoint in this API accepts a version field, and no other endpoint performs this comparison.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Community and Closing Lot Sales

A `PlatformAdmin` registers the community by supplying the declaration's parameters: the association's legal `name` (1 to 120 characters, not blank), the `total_planned_lots` the declaration contemplates (at least 1), the `turnover_threshold_pct` that a percentage-based trigger must reach (between 0.01 and 100.00, two decimals), the declaration's outside `fixed_turnover_date`, the `statute_of_repose_years` used to date defect claims (a whole number from 1 to 15), the opening `reserve_pool_cents` and `reserve_claim_pool_cents` (each zero or more), and the `declarant_monthly_subsidy_cents` the developer funds while the subsidy runs (zero or more). Everything derived starts empty: `sold_lot_count` at 0, `sold_lot_pct` at 0.00, `subsidy_receivable_cents` at 0, `reserve_claim_committed_cents` at 0, `reserve_claim_available_cents` equal to `reserve_claim_pool_cents`, `subsidy_end_date` null, and `budget_forecast_status` at `CURRENT`.

Separately, the administrator opens the transition file itself by naming the `association_id` and the `total_seats` the bylaws fix for the board — an odd number from 3 to 9. A fresh case begins with `governance_status` at `DECLARANT_CONTROL` and `financial_status` at `SUBSIDY_ACTIVE`, hence a `turnover_posture` of `DECLARANT_CONTROL_OPEN`, with `vacant_seats` equal to `total_seats`, `owner_elected_seats_required` at 0, `declarant_appointed_seats` and `owner_elected_seats` at 0, `records_transfer_completeness_pct` at 100.00, `settlement_blocked` false, and `trigger_basis`, `trigger_certified_at` and `trigger_certified_by_user_id` all null. At most one case may exist per association; a second attempt is refused with `ERR_TURNOVER_CASE_EXISTS`.

The `Declarant` records each platted lot against an `association_id` with the `lot_number` printed on the recorded plat (1 to 16 characters, unique within the association — a repeat is `ERR_DUPLICATE_LOT_NUMBER`). A lot's `sale_status` may be supplied at creation as either `UNSOLD`, which is also the default, or `UNDER_CONTRACT`; `CLOSED` is reachable only through the closing transition, so supplying it at creation is an illegal enum member and is rejected with `ERR_INVALID_REQUEST`. The lot's `closing_date` is null until the sale closes.

Closing a sale moves a lot into `CLOSED` from either `UNSOLD` or `UNDER_CONTRACT` — both edges behave identically and take the same `closing_date` from the payload — and is refused with `ERR_LOT_STATE_INVALID` when the lot is already `CLOSED`. The interesting part is the arithmetic it triggers on the association. `sold_lot_count` becomes the number of that association's lots whose `sale_status` is `CLOSED`; lots still `UNSOLD` or `UNDER_CONTRACT` are excluded from that count. `sold_lot_pct` then becomes one hundred multiplied by `sold_lot_count`, divided by `total_planned_lots`, rounded half up to two decimal places — note that the denominator is the declaration's planned lot total, not the number of lot records that happen to exist. Both values are stored on the association, its `version` advances, and the rounded percentage — not the raw quotient — is what the turnover trigger later compares. Truncating instead of rounding half up flips the verdict whenever the exact quotient sits just below the threshold.

### 3.2. Building, Completing and Conveying the Common Areas

Each common area component is registered by the `Declarant` against an `association_id` with a `name` as it appears on the reserve study schedule (1 to 80 characters), a `category` of `AMENITY`, `INFRASTRUCTURE` or `STRUCTURE`, its current `replacement_cost_cents` (zero or more), its total `useful_life_years` (at least 1), its consumed `effective_age_years` (zero or more), and the `promised_completion_date` on which the declarant undertook to reach substantial completion. `build_status` may be supplied as `UNBUILT` (the default) or `IN_PROGRESS`; `COMPLETE` is reachable only through the construction milestone. A new component always starts with `conveyance_status` at `NOT_CONVEYED`, `substantial_completion_date` null and `conveyed_at` null.

Three milestones drive the component forward, and the milestone value in the payload decides both who may record it and which of the component's two dimensions moves. The `Declarant` records `BUILD_COMPLETE`, which is legal from either `UNBUILT` or `IN_PROGRESS` — the two edges are identical in every respect — and which requires an `effective_date` in the payload. It sets `build_status` to `COMPLETE` and writes that `effective_date` into `substantial_completion_date`; because that date is the base of every repose calculation, setting it cascades into a recomputation of `repose_deadline` on every defect claim already open against this component, processed oldest first. A milestone that is not legal from the component's current posture is `ERR_COMPONENT_MILESTONE_INVALID`.

The `Declarant` then records `DEED_TENDERED`, which requires `conveyance_status` to be `NOT_CONVEYED` and `build_status` to already be `COMPLETE` — tendering a deed on an unfinished component is `ERR_COMPONENT_MILESTONE_INVALID` — and moves `conveyance_status` from `NOT_CONVEYED` to `DEED_TENDERED`. Acceptance belongs to the other side: a `TransitionCommittee` records `CONVEYANCE_ACCEPTED`, legal only from `DEED_TENDERED`, which advances `conveyance_status` to `CONVEYED` and stamps `conveyed_at` with the logical clock. Because the set of conveyed components is precisely the input to reserve adequacy, that acceptance cascades: every `DRAFT` reserve study of the association has its `evaluated_method` reset to null, its `adequacy_verdict` reset to `UNDETERMINED` and its `recommended_annual_contribution_cents` reset to 0, so the study must be evaluated again before it can be adopted.

Unbuilt amenities are the declarant's most visible outstanding obligation. An `AMENITY` component whose `build_status` is still `UNBUILT` or `IN_PROGRESS` and whose `promised_completion_date` is earlier than the logical clock is *overdue*, and while any such component exists the association cannot complete either the transfer of governance or the final settlement — both are refused with `ERR_UNBUILT_AMENITY_OUTSTANDING`. A component that is late but not an amenity, and an amenity that is late but already `COMPLETE`, block nothing.

### 3.3. Certifying the Turnover Trigger and Its Consequences

The transition begins when the owner-side committee certifies that the declaration's trigger has fired, supplying a `trigger_basis` of either `PERCENT_SOLD` or `FIXED_DATE`. The case must be in `DECLARANT_CONTROL`, else `ERR_TURNOVER_STAGE_INVALID`. On the `PERCENT_SOLD` basis, the association's `sold_lot_pct` must be greater than or equal to its `turnover_threshold_pct`, with equality sufficient; a shortfall is `ERR_TURNOVER_THRESHOLD_NOT_MET`. On the `FIXED_DATE` basis, the logical clock must have reached the association's `fixed_turnover_date`, with the instant itself sufficient; earlier is `ERR_FIXED_TURNOVER_DATE_NOT_REACHED`. The two bases are checked independently — a community that has sold nothing may still certify on the date, and a community that has crossed the threshold need not wait for it.

Certification is the deepest cascade in the system, and each hop is caused by the hop before it rather than by the request. First, the case's `governance_status` moves `DECLARANT_CONTROL → ELECTION_CALLED`; the supplied `trigger_basis` is recorded, `trigger_certified_at` is stamped from the logical clock, `trigger_certified_by_user_id` captures the acting `X-User-ID`, `owner_elected_seats_required` is computed, and `turnover_posture` is re-derived (with the financial dimension still at `SUBSIDY_ACTIVE`, the posture becomes `TRANSITION_RESTRICTED`).

Entering `ELECTION_CALLED` in turn empties the declarant's side of the board: every director of this case whose `seat_type` is `DECLARANT_APPOINTED` and whose `status` is `SEATED` moves `SEATED → RESIGNED` with `vacated_at` stamped from the clock, processed oldest first, dropping `declarant_appointed_seats` to 0 and freeing those seats into `vacant_seats`.

Emptying the appointed seats is what opens the statutory cancellation right: every vendor contract of the association whose `developer_affiliated` flag is true and whose `status` is `ACTIVE` moves `ACTIVE → CANCELLABLE`, again oldest first, with `cancellation_window_end` set to `trigger_certified_at` plus ninety days. Contracts with an independent vendor are untouched, and so is any affiliated contract not currently `ACTIVE`.

Creating those cancellable obligations makes the adopted operating forecast unreliable, so the association's `budget_forecast_status` moves from `CURRENT` to `STALE` and its `version` advances — and the stale forecast then supersedes every `DRAFT` assessment schedule of the association, oldest first. Five hops, one request.

### 3.4. Converting the Board from Appointment to Election

The size of the owner-elected majority is fixed by arithmetic, not by negotiation. While the case is still in `DECLARANT_CONTROL`, `owner_elected_seats_required` is 0. From certification onward it is two thirds of `total_seats`, rounded up to the next whole seat — so a five-seat board requires four owner-elected directors, and a three-seat board requires two. `declarant_appointed_seats` is the number of directors of the case with `seat_type` `DECLARANT_APPOINTED` and `status` `SEATED`; `owner_elected_seats` is the number with `seat_type` `OWNER_ELECTED` and `status` `SEATED`; and `vacant_seats` is `total_seats` less the sum of those two counts. Directors whose `status` is `RESIGNED` or `RESCINDED` release their seat and are excluded from both counts, and their `vacated_at` records when that happened. The quantity that must hold after every seat mutation, including the resignation cascade of certification and every rescission, is that `total_seats` always equals the number of `SEATED` directors plus `vacant_seats`.

Seating a director takes a `turnover_case_id`, the director's `full_name` (1 to 80 characters) and a `seat_type`. The seat is created with `status` `SEATED` and `seated_by_user_id` set from the acting `X-User-ID`. `DECLARANT_APPOINTED` seats belong to the `Declarant` and are only meaningful while the board is still under declarant control; `OWNER_ELECTED` seats belong to the `ElectionInspector` and are seated once the election has been called. Seating is refused outright when `vacant_seats` is already 0 — the board cannot exceed the size the bylaws fix — with `ERR_SEAT_CAPACITY_EXCEEDED`. Seating is also refused when the acting `X-User-ID` is the same user recorded in `trigger_certified_by_user_id`, with `ERR_SEGREGATION_OF_DUTIES`.

Seating bubbles up into the governance dimension. At the end of a successful seating, if `governance_status` is `ELECTION_CALLED` and `owner_elected_seats` has reached `owner_elected_seats_required`, the case advances `ELECTION_CALLED → ELECTION_HELD` and `turnover_posture` is re-derived. The reverse edge is symmetric. The `ElectionInspector` may rescind a director, which is legal only when that director's `status` is `SEATED` and only when the `seat_type` is `OWNER_ELECTED` — rescinding a resigned director, or an appointed one, is `ERR_DIRECTOR_STATE_INVALID`. Rescission sets `status` to `RESCINDED`, stamps `vacated_at`, decrements `owner_elected_seats` by one and increments `vacant_seats` by one so the seat ledger still balances; and if that drops `owner_elected_seats` below `owner_elected_seats_required` while the case sits in `ELECTION_HELD`, the governance dimension reverts `ELECTION_HELD → ELECTION_CALLED` and the posture is re-derived. The governance dimension is therefore genuinely cyclic: an election can be un-held.

Handing governance over for good is a separate, deliberate act by the committee, which advances the case with a `dimension` of `GOVERNANCE`. It is legal only from `ELECTION_HELD` (otherwise `ERR_TURNOVER_STAGE_INVALID`), requires `records_transfer_completeness_pct` to be at or above 80.00 (otherwise `ERR_RECORDS_INCOMPLETE`), and requires that no overdue unbuilt amenity remains (otherwise `ERR_UNBUILT_AMENITY_OUTSTANDING`). It moves `governance_status` `ELECTION_HELD → OWNER_CONTROL` and re-derives `turnover_posture`, which becomes `OWNER_CONTROL_OPEN` while the financial dimension is still open.

### 3.5. Records, Warranties, Plans and Vendor Contract Assignment

The declarant owes the association a documentary estate, and each piece of it is registered as an item against a `turnover_case_id` with a `category` of `FINANCIAL_RECORDS`, `WARRANTIES`, `PLANS_AND_SPECS`, `VENDOR_CONTRACTS` or `PERMITS`, plus a `required` flag that defaults to true. Items begin `OUTSTANDING`, with `delivered_at` and `rejection_reason` both null.

Completeness is measured only over the required items of the case: it is the number of required items whose `status` is `ACCEPTED`, multiplied by one hundred, divided by the number of required items, rounded half up to two decimal places. A case whose required set is empty is vacuously complete and reports 100.00 rather than failing on a division — which is why a brand-new case starts at 100.00. Items flagged `required` false never move the percentage in either direction, no matter what happens to them. The figure is recomputed whenever an item is registered, accepted or rejected, and it gates the transition twice: the governance handover of §3.4 needs at least 80.00, and final settlement needs exactly 100.00.

The review cycle has three actions on one dispatcher. The `Declarant` sends `DELIVER`, legal from `OUTSTANDING` or from `REJECTED` — the two edges are identical — which sets `status` to `DELIVERED`, stamps `delivered_at` from the logical clock, and clears any `rejection_reason` back to null. The `TransitionCommittee` then either sends `ACCEPT`, legal only from `DELIVERED`, which moves the item `DELIVERED → ACCEPTED` and recomputes the case's completeness; or sends `REJECT`, also legal only from `DELIVERED`, which requires a `rejection_reason` in the payload, records it, moves the item `DELIVERED → REJECTED`, and likewise recomputes completeness. Rejection is not terminal — the declarant may re-deliver, closing the cycle `DELIVERED → REJECTED → DELIVERED`. Any of the three actions attempted from a status the edge does not allow is `ERR_RECORDS_ITEM_STATE_INVALID`.

Vendor contracts are registered by the `Declarant` against an `association_id` and the `component_id` of the component they service, with the `vendor_name` (1 to 80 characters), the `developer_affiliated` flag marking an affiliate of the declarant, the `annual_cost_cents` the operating budget carries (zero or more), and the service window bounded by an inclusive `service_window_start` and an exclusive `service_window_end` that must be strictly later. A component's service windows may not collide: a new window is refused with `ERR_SERVICE_WINDOW_CONFLICT` if it overlaps the window of any existing contract on that same component whose `status` is `ACTIVE` or `CANCELLABLE`, where the existing window is first extended by a thirty-day transition blackout buffer added to its end and the comparison treats each window as including its start instant and excluding its end instant. New contracts begin with `status` `ACTIVE`, `assignment_status` `NOT_REQUESTED` and `cancellation_window_end` null.

Assignment of a contract from the declarant to the association needs consent, and the fork is where the two parties' interests separate. The `Declarant` sends `REQUEST_ASSIGNMENT`, legal only when `assignment_status` is `NOT_REQUESTED` and `status` is `ACTIVE` or `CANCELLABLE`, moving `assignment_status` `NOT_REQUESTED → ASSIGNMENT_REQUESTED`. From there the committee takes exactly one of two branches, and their side effects are disjoint. `CONSENT` moves `assignment_status` `ASSIGNMENT_REQUESTED → CONSENTED` and leaves `status` untouched; because consent is what completes the contract handover, it cascades — every records item of the association's case whose `category` is `VENDOR_CONTRACTS` and whose `status` is `DELIVERED` moves `DELIVERED → ACCEPTED`, oldest first, and the case's `records_transfer_completeness_pct` is then recomputed over those acceptances. `REFUSE_CONSENT` moves `assignment_status` `ASSIGNMENT_REQUESTED → CONSENT_REFUSED` and simultaneously terminates the contract, moving `status` to `TERMINATED_FOR_REFUSAL`; because the refused service has to be re-procured, the association's `budget_forecast_status` is set to `STALE` and its `version` advances. Refusal touches no records item, and consent touches no forecast. Either action from any other `assignment_status` is `ERR_CONTRACT_STATE_INVALID`.

Cancellation is the owners' statutory escape from contracts the developer signed with itself. Only a contract that certification moved into `CANCELLABLE` may be cancelled, and only while the logical clock is at or before its `cancellation_window_end`; a late attempt is `ERR_CANCELLATION_WINDOW_CLOSED`, and an attempt on a contract that is not `CANCELLABLE` is `ERR_CONTRACT_STATE_INVALID`. A successful `CANCEL` moves `status` `CANCELLABLE → CANCELLED`, sets `budget_forecast_status` to `STALE`, advances the association's `version`, and — as a consequence of that staleness — supersedes every `DRAFT` assessment schedule of the association, oldest first. Note carefully that consenting to a contract's assignment does *not* remove it from the cancellable set: only cancellation or refusal of consent does. A developer-affiliated contract left sitting in `CANCELLABLE` blocks settlement.

### 3.6. The Declarant Subsidy Ledger and the Transition Audit

While the subsidy runs, the declarant funds the association's operating deficit, and every movement is a ledger entry posted against an `association_id` with a `direction`, an `amount_cents` of at least 1, and a `period_month` in four-digit-year-hyphen-two-digit-month form. Clients may post `ACCRUAL`, which raises what the declarant owes, or `PAYMENT`, which lowers it. The third direction, `REVERSAL`, is created only by the server. Each entry is stored with `status` `POSTED` and `posted_by_user_id` set from the acting `X-User-ID`, and with `reverses_entry_id` null.

The association's `subsidy_receivable_cents` is the life-to-date balance: the total `amount_cents` of its `POSTED` `ACCRUAL` entries less the total `amount_cents` of its `POSTED` `PAYMENT` entries. There is no time window. Entries whose `status` is `REVERSED` are excluded, and so are the `REVERSAL` mirrors, which exist only to document the undo. The balance may legitimately go negative when payments have run ahead of accruals. Posting an entry recomputes the balance and advances the association's `version`.

Reversal is a compensating operation with a four-hop cascade, and it is available only once per entry. The `Declarant` supplies a `reason`, and the target must have `status` `POSTED`, a `direction` of `ACCRUAL` or `PAYMENT`, and a null `reverses_entry_id` — a mirror is never itself reversible, and any of those three failures is `ERR_SUBSIDY_ENTRY_ALREADY_REVERSED`. The target's `status` becomes `REVERSED`, and the server creates a new entry carrying `direction` `REVERSAL` with the same `amount_cents` and `period_month`, `status` `POSTED`, `posted_by_user_id` from the acting user, and `reverses_entry_id` pointing at the target — discoverable afterwards by filtering the ledger on `reverses_entry_id`. The response returns the reversed target entry, not the mirror. Because the target has left the `POSTED` set, the association's `subsidy_receivable_cents` is recomputed and its `version` advances; the pair must restore the balance to exactly the value it held immediately before the target was posted, and the total of all `REVERSAL` amounts must always equal the total of all `REVERSED` amounts.

Auditing the transition begins with an `Auditor` engaging over a closed accounting period defined by an `association_id`, a `period_start` and a `period_end` at or after it. Periods of one association may not overlap: the new interval is compared as a closed interval, including both endpoints, against every engagement of that association whose `status` is `ENGAGED` or `ISSUED`, so two periods that merely touch at an endpoint already collide, and the rejection is `ERR_AUDIT_PERIOD_OVERLAP`. A new engagement starts `ENGAGED`, with `finding_status` `CLEAN`, `unreconciled_delta_cents` 0, `audited_receivable_snapshot_cents` 0 and `issued_by_user_id` null.

Issuing the report — legal only from `ENGAGED`, otherwise `ERR_AUDIT_NOT_ISSUABLE` — moves the engagement `ENGAGED → ISSUED`, records `issued_by_user_id`, and freezes the in-window balance. `audited_receivable_snapshot_cents` is the total of the association's `POSTED` `ACCRUAL` amounts less the total of its `POSTED` `PAYMENT` amounts, restricted to entries whose `period_month` lies inside the engagement's window, where the window runs from the year-and-month of `period_start` to the year-and-month of `period_end` with both bounds included and the comparison made on the year-month strings themselves. That snapshot is frozen once and never recomputed. `unreconciled_delta_cents` is then the association's current `subsidy_receivable_cents` less that frozen snapshot, and `finding_status` is `CLEAN` when the delta is exactly 0 and `EXCEPTION_NOTED` for any other value — there is no tolerance band.

Drift is the point of the design. The delta and the `finding_status` of every `ISSUED` engagement are recomputed after every later movement of the association's receivable, whether that movement comes from a fresh posting or from a reversal. Because the snapshot never moves, an entry posted outside the audited window, or a post-issuance reversal of an in-window entry, shows up as a non-zero delta and flips the engagement to `EXCEPTION_NOTED`. Whenever any `ISSUED` engagement of the association stands at `EXCEPTION_NOTED`, the association's turnover case has `settlement_blocked` set to true; once latched, that flag is not cleared by any later ledger movement, and it bars settlement.

### 3.7. Reserve Funding Adequacy and Its Adoption

The committee opens a reserve study against an `association_id`, recording the `funding_method` the study was written under — either `COMPONENT_FULL_FUNDING` or `CASH_FLOW` — together with the `planned_annual_contribution_cents` it assumes and the year-one `projected_annual_expenditure_cents` before escalation, both zero or more. A new study is a `DRAFT` with `evaluated_method` null, `adequacy_verdict` `UNDETERMINED`, `recommended_annual_contribution_cents` 0, `component_count` 0, `fully_funded_balance_cents` 0, `percent_funded` 0.00 and `min_projected_balance_cents` 0. Opening a study supersedes any other `DRAFT` study of the same association, so only one draft is ever live.

Evaluation is an explicit, repeatable act: the committee sends `RECOMPUTE` with a `method`, legal only while the study is `DRAFT` (otherwise `ERR_NOT_IN_DRAFT`) and requiring the `method` in the payload (otherwise `ERR_INVALID_REQUEST`). The supplied `method` is written to `evaluated_method` and drives the evaluation, so a single run may deliberately evaluate a study under a method other than the `funding_method` it was recorded with. Each run overwrites the previous verdict.

Two parts of the evaluation are method-independent. The **funded component set** is the association's components whose `build_status` is `COMPLETE` **and** whose `conveyance_status` is `CONVEYED`; `component_count` is its size. A component that is finished but not yet accepted by the association contributes nothing. `fully_funded_balance_cents` is the sum, over that set, of each component's `replacement_cost_cents` multiplied by the lesser of its `effective_age_years` and its `useful_life_years`, divided by its `useful_life_years`, with each component's share rounded down to whole cents before it joins the sum. `percent_funded` is 0.00 when that balance is 0; otherwise it is one hundred multiplied by the association's `reserve_pool_cents`, divided by `fully_funded_balance_cents`, rounded half up to two decimal places.

Under `COMPONENT_FULL_FUNDING`, an empty or valueless funded set — a `fully_funded_balance_cents` of 0 — leaves `adequacy_verdict` at `UNDETERMINED`, `recommended_annual_contribution_cents` at 0 and `min_projected_balance_cents` at 0. Otherwise the verdict reads off `percent_funded` against two breakpoints, both inclusive at the lower bound: `ADEQUATE` at 70.00 percent funded or better, `MARGINAL` at 30.00 percent or better but below 70.00, and `DEFICIENT` below 30.00. The recommendation amortises the funding gap over a ten-year recovery horizon: `fully_funded_balance_cents` less the association's `reserve_pool_cents`, divided by ten and rounded up to the next whole cent, with the result floored at zero so an over-funded association is never told to contribute a negative amount. `min_projected_balance_cents` stays 0 under this method.

Under `CASH_FLOW` the verdict comes from a five-year walk instead, and the funded component set is irrelevant to it. The walk starts with the association's `reserve_pool_cents` as the year-zero balance. For each of the five following years, in order, that year's expenditure is the study's `projected_annual_expenditure_cents` escalated by three percent per year of the walk — the base expenditure multiplied by one hundred plus three times the year number, divided by one hundred, rounded down to whole cents — and the year's balance is the previous year's balance plus the study's `planned_annual_contribution_cents` less that year's expenditure. `min_projected_balance_cents` is the smallest of the six balances, with the year-zero opening balance participating in the comparison. The verdict is `ADEQUATE` when that minimum is zero or better, `MARGINAL` when it is negative but no deeper than 500,000 cents below zero, and `DEFICIENT` when it falls below that floor. The recommendation is the study's `planned_annual_contribution_cents` plus the shortfall spread over the horizon: the amount by which the minimum falls below zero (zero if it never does), divided by five and rounded up to the next whole cent. This method never yields `UNDETERMINED`, so the very same data can be `ADEQUATE` under `CASH_FLOW` and `UNDETERMINED` under `COMPONENT_FULL_FUNDING`.

Adoption makes a study the association's funding baseline. `ADOPT` is legal only while the study is `DRAFT`, else `ERR_NOT_IN_DRAFT`, and only once an evaluation has actually run — `evaluated_method` must not be null and `adequacy_verdict` must not be `UNDETERMINED`, else `ERR_ADEQUACY_NOT_EVALUATED`. On success the study's `status` moves `DRAFT → ADOPTED`, and as a consequence the association's previously `ADOPTED` study moves `ADOPTED → SUPERSEDED`, so exactly one adopted study exists at a time and the budget re-forecast reads the newest recommendation from that point on. Remember that accepting a conveyance later invalidates any live draft, as described in §3.2.

### 3.8. Construction Defect Claims and the Statute of Repose

The committee opens a claim against a specific component before the statute runs out, supplying the `association_id`, the `component_id` of the allegedly defective component, a `defect_summary` narrative of 1 to 400 characters, and both measures of damages: the `repair_cost_estimate_cents` cost-to-repair figure and the `diminution_value_cents` diminution-in-value figure, each at least 1. A claim opens `INVESTIGATING` with `negotiation_round` 0, `valuation_basis` null, `reserve_subtotal_cents` 0, `litigation_admin_fee_cents` 0, `reserved_amount_cents` 0 and `settlement_amount_cents` null.

The claim's `repose_deadline` is derived, not supplied. It is null while the component has no `substantial_completion_date`. Once that date exists, the deadline is that instant advanced by the association's `statute_of_repose_years` whole calendar years, landing on the same month and day and preserving the time of day; where the target year has no such day — a 29 February base in a non-leap year — the deadline clamps back to 28 February. The deadline is computed when the claim is opened and recomputed as a cascade of the component's `BUILD_COMPLETE` milestone; a later edit of the association's repose parameter cannot move an already-computed deadline, because that parameter is supplied only at association registration.

Notice is the committee's first formal move: `NOTICE` is legal only from `INVESTIGATING` (otherwise `ERR_CLAIM_STATE_INVALID`), requires the referenced component's `conveyance_status` to be `CONVEYED` (otherwise `ERR_COMPONENT_NOT_CONVEYED`), and requires a non-null `repose_deadline` with the logical clock at or before it — the deadline instant itself is still inside the period. A claim noticed too late, or noticed with no deadline at all, is refused with `ERR_REPOSE_PERIOD_EXPIRED`. Success moves the claim `INVESTIGATING → NOTICED`.

The negotiation is a genuine loop. The `Declarant` may answer a noticed claim with `REJECT`, legal only from `NOTICED`, moving it `NOTICED → REJECTED_BY_DEVELOPER`. The committee may then send `REINVESTIGATE`, legal only from `REJECTED_BY_DEVELOPER`, which returns the claim `REJECTED_BY_DEVELOPER → INVESTIGATING` and increments `negotiation_round` by one — closing the cycle `INVESTIGATING → NOTICED → REJECTED_BY_DEVELOPER → INVESTIGATING`. The loop is bounded: re-investigation requires `negotiation_round` to be strictly below three completed rounds, so the fourth attempt is refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`.

Reserving a claim commits association money and is the system's tiered calculation. `RESERVE` is legal from either `NOTICED` or `REJECTED_BY_DEVELOPER` — the two edges behave identically — and requires a `valuation_basis` in the payload, either `REPAIR_COST` or `DIMINUTION`. That choice selects `reserve_subtotal_cents`: the claim's `repair_cost_estimate_cents` under `REPAIR_COST`, or its `diminution_value_cents` under `DIMINUTION`. The evaluation order from there is pinned and normative: first the subtotal, then the fee tier **selected from the subtotal alone**, then the fee, then the total. The tier rate is twelve percent while the subtotal is below 2,000,000 cents, nine percent while it is below 10,000,000 cents, and six percent at or above that — each tier bound including its lower edge and excluding its upper. `litigation_admin_fee_cents` is the subtotal multiplied by that rate, rounded half up to whole cents, and `reserved_amount_cents` is the subtotal plus the fee. Re-selecting the tier from the combined total, or iterating the two steps to a fixed point, produces a different and incorrect figure even though the fee schedule is captioned as a rate on total claim exposure.

The reserve must fit the pool. `reserved_amount_cents` must be less than or equal to the association's `reserve_claim_available_cents`, with equality allowed; anything larger is `ERR_CLAIM_RESERVE_INSUFFICIENT`, evaluated after every other check on the request. On success the claim moves to `RESERVED`, its `valuation_basis`, `reserve_subtotal_cents`, `litigation_admin_fee_cents` and `reserved_amount_cents` are written, the association's `reserve_claim_committed_cents` grows by the reserved amount, its `reserve_claim_available_cents` is recomputed as `reserve_claim_pool_cents` less `reserve_claim_committed_cents`, and its `version` advances. Because the available figure already excludes every other `RESERVED` claim of the association, the pool cannot be over-committed.

Two exits release that money and one does not. The `Declarant` may accept a claim with `ACCEPT`, legal from either `NOTICED` or `RESERVED` and requiring a `settlement_amount_cents` in the payload; the claim moves to `SETTLED` and the accepted amount is recorded. Accepting from `NOTICED` releases nothing, because `reserved_amount_cents` is still 0. Accepting from `RESERVED` additionally reduces the association's `reserve_claim_committed_cents` by exactly `reserved_amount_cents`, resets the claim's `reserved_amount_cents` to 0, recomputes `reserve_claim_available_cents` and advances the association's `version`. The committee may abandon a claim with `WITHDRAW`, legal from `INVESTIGATING`, `NOTICED`, `REJECTED_BY_DEVELOPER` or `RESERVED`; the claim moves to `WITHDRAWN`, and the same compensating release runs when the claim was `RESERVED` while a withdrawal from `INVESTIGATING` (or any other unreserved status) moves no money at all. After every forward-and-compensating pair, `reserve_claim_committed_cents` plus `reserve_claim_available_cents` still equals `reserve_claim_pool_cents`. Any claim action attempted from a status its edge does not allow is `ERR_CLAIM_STATE_INVALID`.

Claims that nobody pursues die by the statute. A committee-driven sweep over the association bars every claim whose `status` is still `INVESTIGATING` and whose `repose_deadline` is non-null and strictly earlier than the logical clock, moving each `INVESTIGATING → TIME_BARRED`, oldest first. Claims with a null `repose_deadline` are never swept, and neither are claims in any other status. The sweep reports what it did: `swept_claim_count` as an integer and `time_barred_claim_ids` as the list of affected claim identifiers.

### 3.9. Re-forecasting the Budget and Settling the Transition

Ending the subsidy and opening the audit window are one event, not two, so that the recorded end date can never drift from the financial dimension. The committee advances the case with a `dimension` of `FINANCIAL`; from `SUBSIDY_ACTIVE` the request must carry a `subsidy_end_date` (otherwise `ERR_INVALID_REQUEST`) and at least one audit engagement of the association must exist in `ENGAGED` or `ISSUED` (otherwise `ERR_TRANSITION_AUDIT_MISSING`); a request from any other financial state is `ERR_TURNOVER_STAGE_INVALID`. On success `financial_status` moves `SUBSIDY_ACTIVE → AUDIT_IN_PROGRESS`, the supplied date is written to the association's `subsidy_end_date`, `budget_forecast_status` is set to `STALE` and the association's `version` advances; the stale forecast then supersedes every `DRAFT` assessment schedule of the association, oldest first, and `turnover_posture` is re-derived.

Only then can the owners re-forecast. Creating an assessment schedule takes an `association_id`, the `fiscal_year` it funds (a calendar year from 2024 to 2035, running from the first day of January through the last day of December), the re-forecast `projected_operating_cost_cents` for that year excluding both the reserve contribution and the subsidy offset, and the `expected_association_version` of §2.10. The association's financial dimension must have left `SUBSIDY_ACTIVE`, else `ERR_SUBSIDY_STILL_ACTIVE`, and an `ADOPTED` reserve study must exist, else `ERR_RESERVE_STUDY_NOT_ADOPTED`.

The re-forecast then runs as a waterfall. `billable_lot_count` is the number of the association's lots whose `sale_status` is `CLOSED` or `UNDER_CONTRACT`; lots still `UNSOLD` are excluded from the divisor because the declarant absorbs their share of the deficit — note that this set is deliberately wider than the `CLOSED`-only numerator of the turnover trigger. `reserve_contribution_cents` is the `recommended_annual_contribution_cents` of the association's single `ADOPTED` study. `subsidy_offset_cents` is the association's `declarant_monthly_subsidy_cents` multiplied by the number of months of the fiscal year still covered by the subsidy, counted as those of the year's twelve year-month labels that sort strictly before the year-month of the association's `subsidy_end_date`, and taken as zero when that date is null. `annual_requirement_cents` is `projected_operating_cost_cents` plus `reserve_contribution_cents` less `subsidy_offset_cents`.

The rounding order in the final steps is pinned: the per-lot figure is derived first and the annual total is then multiplied back up from it. `per_lot_monthly_assessment_cents` is `annual_requirement_cents` divided by `billable_lot_count` times twelve months, rounded **up** to the next whole cent. `annual_budget_total_cents` is that per-lot figure multiplied by `billable_lot_count` and by twelve. `residual_cents` is `annual_budget_total_cents` less `annual_requirement_cents` — a small over-collection that arises precisely because of the ceiling. Summing first and rounding once at the end would force the total to equal the requirement and the residual to zero; that order is forbidden.

Two more derived fields govern whether the owners get a say. `increase_pct_vs_prior` is 0.00 when the association has never adopted a schedule; otherwise it is one hundred multiplied by the difference between this schedule's `per_lot_monthly_assessment_cents` and that of the currently `ADOPTED` schedule, divided by the adopted schedule's `per_lot_monthly_assessment_cents`, rounded half up to two decimal places. `owner_vote_required` is true only when that percentage is **strictly greater** than the statutory cap of 20.00 percent; an increase that rounds to exactly 20.00 needs no vote. The schedule is created as a `DRAFT` with `owner_vote_ratified` false, it supersedes any other `DRAFT` schedule of the association, and the association's `version` advances.

Adoption is the committee's final budget act. It is legal only from `DRAFT`, else `ERR_NOT_IN_DRAFT`, and when `owner_vote_required` is true the payload must carry `owner_vote_ratified` set to true, else `ERR_OWNER_VOTE_REQUIRED`; when no vote is required, the flag is recorded as supplied and as false when omitted. On success the schedule moves `DRAFT → ADOPTED`, the association's previously `ADOPTED` schedule moves `ADOPTED → SUPERSEDED` (it remains the increase baseline only until then), the schedule's `residual_cents` is credited to the association's `reserve_pool_cents`, `budget_forecast_status` returns from `STALE` to `CURRENT`, and the association's `version` advances. That credit deliberately does **not** re-evaluate any reserve study: `percent_funded` moves only on an explicit re-evaluation.

Settlement closes the transition, and it is the most heavily guarded transition in the system. The committee advances the `FINANCIAL` dimension a second time, and every one of the following must hold: `financial_status` is `AUDIT_IN_PROGRESS` and `governance_status` is already `OWNER_CONTROL`, else `ERR_TURNOVER_STAGE_INVALID`; `settlement_blocked` is false and at least one audit engagement of the association is `ISSUED` with `finding_status` `CLEAN`, else `ERR_SETTLEMENT_BLOCKED`; `records_transfer_completeness_pct` is exactly 100.00, else `ERR_RECORDS_INCOMPLETE`; no defect claim of the association remains in `INVESTIGATING`, `NOTICED` or `REJECTED_BY_DEVELOPER`, else `ERR_CLAIM_STATE_INVALID`; no developer-affiliated vendor contract of the association is still `CANCELLABLE`, else `ERR_ASSIGNMENT_CONSENT_REQUIRED`; and no overdue unbuilt amenity remains, else `ERR_UNBUILT_AMENITY_OUTSTANDING`. When all of them hold, `financial_status` moves `AUDIT_IN_PROGRESS → SETTLED`, and because governance is already `OWNER_CONTROL` the re-derived `turnover_posture` becomes `SETTLED_LOCKED` — after which the community's books are closed and every association-scoped mutation listed in §2.8 is refused with `ERR_TURNOVER_SETTLED_LOCKED`.

## 4. Endpoint Definitions

Operations that bring a new resource into existence return `201 Created`. Operations that modify an existing resource — every transition, action, milestone, sweep and clock movement — return `200 OK`, as do all reads. Where the description below names several actions on one path, the payload discriminator (`action`, `milestone`, `dimension` or `seat_type`) selects both the behaviour and the role permitted to invoke it, as specified in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/hoa/associations` | Register an association with its declaration parameters | PlatformAdmin |
| GET | `/hoa/associations/{id}` | Read one association including every derived finance counter | Any authenticated role |
| GET | `/hoa/associations/{id}/lots` | List the association's lots, optionally filtered by `sale_status` | Any authenticated role |
| GET | `/hoa/associations/{id}/components` | List the association's common area components, optionally filtered by `build_status`, `conveyance_status` or `category` | Any authenticated role |
| GET | `/hoa/associations/{id}/turnover-cases` | List the association's turnover cases (zero or one) | Any authenticated role |
| GET | `/hoa/associations/{id}/reserve-studies` | List the association's reserve studies, optionally filtered by `status` | Any authenticated role |
| GET | `/hoa/associations/{id}/audit-engagements` | List the association's transition audit engagements, optionally filtered by `status` | Any authenticated role |
| GET | `/hoa/associations/{id}/assessment-schedules` | List the association's assessment schedules, optionally filtered by `fiscal_year` or `status` | Any authenticated role |
| POST | `/hoa/associations/{id}/repose-sweep` | Bar the association's still-investigating claims whose repose period has run | TransitionCommittee |
| POST | `/hoa/lots` | Record a platted lot | Declarant |
| POST | `/hoa/lots/{id}/close-sale` | Close the sale of a lot, moving it into the turnover-trigger numerator | Declarant |
| POST | `/hoa/components` | Register a common area component on the reserve schedule | Declarant |
| POST | `/hoa/components/{id}/milestones` | Record a `BUILD_COMPLETE`, `DEED_TENDERED` or `CONVEYANCE_ACCEPTED` milestone | Declarant, TransitionCommittee |
| POST | `/hoa/turnover-cases` | Open the turnover case for an association | PlatformAdmin |
| GET | `/hoa/turnover-cases/{id}` | Read one turnover case with both dimensions, the derived posture and the seat ledger | Any authenticated role |
| POST | `/hoa/turnover-cases/{id}/certify-trigger` | Certify that the declaration's turnover trigger has fired and call the election | TransitionCommittee |
| POST | `/hoa/turnover-cases/{id}/advance` | Advance one dimension of the turnover case | TransitionCommittee |
| GET | `/hoa/turnover-cases/{id}/records-items` | List the case's records transfer items, optionally filtered by `category` or `status` | Any authenticated role |
| GET | `/hoa/turnover-cases/{id}/directors` | List the case's board seats, optionally filtered by `seat_type` or `status` | Any authenticated role |
| POST | `/hoa/directors` | Seat a board director | Declarant, ElectionInspector |
| POST | `/hoa/directors/{id}/rescind` | Rescind a seated owner-elected director, freeing the seat | ElectionInspector |
| POST | `/hoa/records-items` | Register a record, warranty, plan, permit or contract item the declarant owes | Declarant |
| POST | `/hoa/records-items/{id}/transitions` | Drive a records item through `DELIVER`, `ACCEPT` or `REJECT` | Declarant, TransitionCommittee |
| POST | `/hoa/subsidy-entries` | Post a declarant subsidy accrual or payment to the ledger | Declarant |
| GET | `/hoa/subsidy-entries` | Filtered list of ledger entries by `association_id`, `reverses_entry_id`, `direction` or `status` | Any authenticated role |
| GET | `/hoa/subsidy-entries/{id}` | Read one declarant subsidy ledger entry | Any authenticated role |
| POST | `/hoa/subsidy-entries/{id}/reverse` | Reverse a posted entry, creating the mirror row that documents the undo | Declarant |
| POST | `/hoa/audit-engagements` | Engage the transition auditor over a closed accounting period | Auditor |
| POST | `/hoa/audit-engagements/{id}/issue` | Issue the transition audit report, freezing the in-window receivable snapshot | Auditor |
| POST | `/hoa/reserve-studies` | Open a draft reserve study for the association | TransitionCommittee |
| POST | `/hoa/reserve-studies/{id}/actions` | Act on a draft study: `RECOMPUTE` its adequacy or `ADOPT` it as the baseline | TransitionCommittee |
| POST | `/hoa/defect-claims` | Open a construction defect claim against a common area component | TransitionCommittee |
| GET | `/hoa/defect-claims` | Filtered list of defect claims by `association_id`, `component_id` or `status` | Any authenticated role |
| GET | `/hoa/defect-claims/{id}` | Read one claim including its reserve breakdown and repose deadline | Any authenticated role |
| POST | `/hoa/defect-claims/{id}/actions` | Drive a claim through `NOTICE`, `REJECT`, `REINVESTIGATE`, `RESERVE`, `ACCEPT` or `WITHDRAW` | TransitionCommittee, Declarant |
| POST | `/hoa/vendor-contracts` | Register a service contract on a common area component | Declarant |
| GET | `/hoa/vendor-contracts` | Filtered list of contracts by `association_id`, `component_id`, `developer_affiliated` or `status` | Any authenticated role |
| GET | `/hoa/vendor-contracts/{id}` | Read one contract including assignment posture and cancellation window | Any authenticated role |
| POST | `/hoa/vendor-contracts/{id}/actions` | Act on a contract: `REQUEST_ASSIGNMENT`, `CONSENT`, `REFUSE_CONSENT` or `CANCEL` | Declarant, TransitionCommittee |
| POST | `/hoa/assessment-schedules` | Re-forecast the operating budget and derive the post-subsidy per-lot assessment | TransitionCommittee |
| POST | `/hoa/assessment-schedules/{id}/adopt` | Adopt a draft assessment schedule | TransitionCommittee |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving capability) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ASSOCIATION_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_TURNOVER_CASE_NOT_FOUND` | 404 |
| `ERR_COMPONENT_NOT_FOUND` | 404 |
| `ERR_DEFECT_CLAIM_NOT_FOUND` | 404 |
| `ERR_VENDOR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_SUBSIDY_ENTRY_NOT_FOUND` | 404 |
| `ERR_RESERVE_STUDY_NOT_FOUND` | 404 |
| `ERR_RECORDS_ITEM_NOT_FOUND` | 404 |
| `ERR_AUDIT_ENGAGEMENT_NOT_FOUND` | 404 |
| `ERR_DIRECTOR_NOT_FOUND` | 404 |
| `ERR_ASSESSMENT_SCHEDULE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_ASSOCIATION_VERSION` | 412 |
| `ERR_TURNOVER_SETTLED_LOCKED` | 409 |
| `ERR_TURNOVER_STAGE_INVALID` | 409 |
| `ERR_TURNOVER_CASE_EXISTS` | 409 |
| `ERR_LOT_STATE_INVALID` | 409 |
| `ERR_COMPONENT_MILESTONE_INVALID` | 409 |
| `ERR_CLAIM_STATE_INVALID` | 409 |
| `ERR_CONTRACT_STATE_INVALID` | 409 |
| `ERR_RECORDS_ITEM_STATE_INVALID` | 409 |
| `ERR_DIRECTOR_STATE_INVALID` | 409 |
| `ERR_SUBSIDY_ENTRY_ALREADY_REVERSED` | 409 |
| `ERR_AUDIT_NOT_ISSUABLE` | 409 |
| `ERR_NOT_IN_DRAFT` | 409 |
| `ERR_ADEQUACY_NOT_EVALUATED` | 409 |
| `ERR_COMPONENT_NOT_CONVEYED` | 409 |
| `ERR_SUBSIDY_STILL_ACTIVE` | 409 |
| `ERR_RESERVE_STUDY_NOT_ADOPTED` | 409 |
| `ERR_TRANSITION_AUDIT_MISSING` | 409 |
| `ERR_AUDIT_PERIOD_OVERLAP` | 409 |
| `ERR_SERVICE_WINDOW_CONFLICT` | 409 |
| `ERR_DUPLICATE_LOT_NUMBER` | 409 |
| `ERR_ASSIGNMENT_CONSENT_REQUIRED` | 422 |
| `ERR_UNBUILT_AMENITY_OUTSTANDING` | 422 |
| `ERR_RECORDS_INCOMPLETE` | 422 |
| `ERR_REPOSE_PERIOD_EXPIRED` | 422 |
| `ERR_CANCELLATION_WINDOW_CLOSED` | 422 |
| `ERR_TURNOVER_THRESHOLD_NOT_MET` | 422 |
| `ERR_FIXED_TURNOVER_DATE_NOT_REACHED` | 422 |
| `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` | 422 |
| `ERR_SEAT_CAPACITY_EXCEEDED` | 422 |
| `ERR_OWNER_VOTE_REQUIRED` | 422 |
| `ERR_CLAIM_RESERVE_INSUFFICIENT` | 422 |
| `ERR_SETTLEMENT_BLOCKED` | 422 |
