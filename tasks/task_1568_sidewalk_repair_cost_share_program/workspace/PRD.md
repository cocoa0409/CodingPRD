# Sidewalk Cost Share API — Product Requirements Document

## 1. Introduction

Municipal sidewalk maintenance sits at an awkward intersection of public safety, private responsibility, and constrained budgets. Under the city's sidewalk ordinance, the abutting property owner is responsible for the condition of the walk fronting their parcel, yet the city carries the duty to inventory defects, notify owners, enforce compliance deadlines, coordinate with urban forestry when street trees displace the pavement, and — when owners do not act — step in with its own contractors and recover costs through liens. Layered on top of this enforcement track is a cost-share program: owners who repair promptly after receiving a notice may apply for a city subsidy drawn from an annual appropriation, with the city's share rising for hardship-qualified owners and for parcels on higher-classification streets.

This document specifies the API that administers that program end to end. It covers the condition inventory (parcels, sidewalk segments, and classified defects), the notice-to-repair lifecycle with its appeals track, the cost-share application pipeline from submission through obligation and reimbursement, the neighborhood bid-pooling machinery used when the city must perform the work itself, the urban-forestry review loop for tree-root conflicts, and the lien lifecycle with interest accrual and foreclosure referral. Seven roles interact with the system under strict segregation-of-duties rules, all time-sensitive behavior is evaluated against a controllable logical clock rather than the wall clock, and every dollar movement is pinned to a per-component rounding discipline so that the program ledger, the owner's bill, and the contractor's bid arithmetic agree to the cent.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a role value outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose authenticated role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The seven role names, spelled exactly as the API expects them, are `ProgramCoordinator`, `Inspector`, `PropertyOwner`, `Contractor`, `ForestryOfficer`, `FinanceOfficer`, and `HearingOfficer`.

Two of these roles are entity-backed. When `X-User-Role` is `PropertyOwner`, `X-User-ID` is the `id` of the acting `PropertyOwner`; ownership checks on any resource that resolves through a parcel chain compare the parcel's `owner_id` to `X-User-ID`, and an `X-User-ID` that does not reference an existing `PropertyOwner` fails as `ERR_PROPERTY_OWNER_NOT_FOUND`. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting `Contractor`; ownership checks on bids and awarded work compare the relevant `contractor_id` to `X-User-ID`, and an unknown contractor identifier fails as `ERR_CONTRACTOR_NOT_FOUND`. Acting on a resource outside one's ownership scope — an owner appealing a notice on someone else's parcel, a contractor withdrawing a bid it did not submit — is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

The remaining five roles carry opaque identities. When `X-User-Role` is `ProgramCoordinator`, `Inspector`, `ForestryOfficer`, `FinanceOfficer`, or `HearingOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records these identifiers where a workflow demands it — for example as `recorded_by_inspector_id` on a `Defect`, `issued_by_user_id` on a `RepairNotice`, `decided_by_user_id` on a `ForestryReview`, `appeal_decided_by_user_id` on a decided appeal, or `inspector_id` on an `InspectionRecord` — but never compares them to any entity's `id`. Certain workflows then compare two recorded opaque identifiers against each other to enforce segregation of duties, rejecting conflicts with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

Read endpoints are shared across all seven roles. When the caller's role is `PropertyOwner`, owner-scoped list results are filtered to resources whose parcel chain yields `owner_id` equal to the caller's `X-User-ID`.

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, must be at least 1, and may not exceed 100; `offset` defaults to 0. Every list response reports `limit`, `offset`, `total_count`, and `has_more` in the `meta` object. List results are sorted by `created_at` in ascending order unless a more specific rule says otherwise.

### 2.4. The Logical Program Clock

Deadlines, windows, accrual day-counts, and expiry checks throughout this program are evaluated against a **logical clock** maintained by the server, never against wall-clock time. Before any operator intervention the logical clock reads exactly `2026-08-01T00:00:00Z`. A `ProgramCoordinator` may advance or set the clock through a test-driving capability that accepts a `to_iso8601` instant and answers with the resulting `current_utc`; once set, the server holds that value until the next explicit set. Date-valued fields such as work windows and insurance validity are compared at day granularity against this clock, and datetime-valued deadlines are compared as instants.

### 2.5. Common Resource Properties and Optimistic Concurrency Control

Every persisted resource carries an `id` minted by the server as a UUID with no type prefix, plus a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Unless otherwise noted, resources also carry an `updated_at` timestamp of the same format and an integer `version` that increments by exactly one on every mutation of that resource, with `updated_at` refreshed at the same moment. The single exception is `InspectionRecord`, an append-only evidentiary row that carries only `id` and `created_at`; both `updated_at` and `version` are absent from it. State transitions described in §3 increment the `version` of the entity being transitioned, and cascade effects increment the versions of every other entity they mutate, as each workflow specifies.

Three write operations are guarded by optimistic concurrency control, each pinned to the version of a parent entity the client has observed:

- Extending a notice's deadline requires the request to carry `expected_notice_version`, the client's last observed `version` of that `RepairNotice`. If the value does not match the notice's current `version` — because the notice has been mutated since the client read it — the extension is rejected with `ERR_STALE_NOTICE_VERSION` (HTTP 412), and the client must re-read the notice and retry.
- Submitting a bid requires `expected_batch_version`, the client's last observed `version` of the target `BidBatch`. A bid's price is computed against the batch's work-item list, and each accepted bid creation itself increments the batch's `version`, so a request carrying an earlier expected version fails deterministically with `ERR_STALE_BATCH_VERSION` (HTTP 412).
- Adjusting a cycle's appropriation requires `expected_program_cycle_version`, the client's last observed `version` of the `ProgramCycle`. A mismatch with the cycle's current `version` is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412).

Endpoints not named in the three rules above do not accept a version field at all.

### 2.6. Money, Measurement, and Rounding Discipline

All monetary values are integer cents; no fractional cents exist anywhere in the system. Where a computation produces a fraction, it is rounded half-up to the nearest whole cent, and — critically — rounding is applied **per component, in the pinned order each calculation specifies, before the components are summed**. A single end-to-end computation that rounds only at the end produces different cents and is non-conformant. Award and fee arithmetic likewise pins a multiply-first, then divide, then round order where a share of a whole is taken.

Two measurement conventions complete the picture. Measured defect offsets are recorded in inches and compared exactly as given: two-decimal inputs participate in threshold comparisons without any rounding of the input itself. The area-weighted condition index is the sole non-integer measurement in the system and is rounded half-up to one decimal place.

### 2.7. Validation Order and Identifier Resolution

When several checks could reject the same request, the server evaluates them in a fixed priority order and reports only the first failure. The order is:

1. **Priority 0 — request shape.** Malformed payloads fail before anything else where no header is needed to parse the body, and otherwise immediately after priority 1: unknown payload fields, missing required fields, wrongly typed values, non-positive quantities, invalid enum members, and windows whose start is not strictly before their end all fail with `ERR_INVALID_REQUEST` (HTTP 400).
2. **Priority 1 — authentication.** Header presence and role recognition per §2.1, failing as `ERR_UNAUTHENTICATED`. For entity-backed roles, an `X-User-ID` that references no existing owner or contractor surfaces here with the corresponding not-found error.
3. **Priority 2 — role authorization.** The caller's role must appear in the endpoint's role list, else `ERR_FORBIDDEN_ROLE`.
4. **Priority 3 — ownership and scope.** Entity-backed actors may act only on resources their ownership chain covers, else `ERR_OWNERSHIP_MISMATCH`.
5. **Priority 4 — existence.** Path identifiers and body foreign keys must reference existing resources, validated left-to-right: path parameters first, then body fields in their declaration order. Each resource type has its own not-found error — `ERR_PROGRAM_CYCLE_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`, `ERR_SEGMENT_NOT_FOUND`, `ERR_DEFECT_NOT_FOUND`, `ERR_REPAIR_NOTICE_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_BID_BATCH_NOT_FOUND`, `ERR_WORK_ITEM_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_FORESTRY_REVIEW_NOT_FOUND`, and `ERR_LIEN_CASE_NOT_FOUND` (all HTTP 404). Nested retrieval follows the same left-to-right discipline: in a path such as a defect's forestry-review listing or a notice's inspection listing, the parent identifier is resolved before the subordinate collection is produced.
6. **Priority 5 — state preconditions.** The target resource must be in the state the requested transition requires, else the transition's specific state error (HTTP 409): `ERR_INVALID_CYCLE_STATE`, `ERR_CYCLE_NOT_OPEN`, `ERR_INVALID_NOTICE_STATE`, `ERR_INVALID_DEFECT_STATE`, `ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_BATCH_STATE`, `ERR_INVALID_WORK_ITEM_STATE`, `ERR_INVALID_BID_STATE`, `ERR_INVALID_FORESTRY_STATE`, `ERR_INVALID_LIEN_STATE`, or `ERR_NOTICE_NOT_COMPLIANT`.
7. **Priority 6 — optimistic concurrency.** On the three OCC-guarded writes of §2.5, the expected-version field must equal the parent's current `version`, else the matching stale-version error (HTTP 412).
8. **Priority 7 — referential composition.** Cross-entity integrity rules of §3, returning `ERR_DEFECT_NOT_IN_PARCEL`, `ERR_DEFECT_UNDER_ACTIVE_NOTICE`, `ERR_NO_ELIGIBLE_DEFECTS`, `ERR_CITY_PARCEL_NOT_NOTICABLE`, `ERR_NOTICE_ALREADY_POOLED`, `ERR_INVALID_NOTICE_REFERENCE`, or `ERR_PARCEL_NOTICE_MISMATCH` (all HTTP 422).
9. **Priority 8 — segregation and safety gates.** `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) and `ERR_FORESTRY_NOT_CLEARED` (HTTP 409), applied to the four operations enumerated in §3.4 and §3.7: appeal decisions, compliance inspections, work-item verification, and batch award.
10. **Priority 9 — temporal windows.** Clock comparisons returning `ERR_APPEAL_WINDOW_CLOSED`, `ERR_BID_DEADLINE_PASSED`, `ERR_BID_WINDOW_STILL_OPEN`, `ERR_WORK_WINDOW_NOT_REACHED`, `ERR_APPLICATION_EXPIRED`, or `ERR_FORECLOSURE_TOO_EARLY` (all HTTP 422).
11. **Priority 10 — uniqueness and capacity constraints.** `ERR_DUPLICATE_PARCEL_NUMBER`, `ERR_DUPLICATE_SEGMENT_CODE`, `ERR_DUPLICATE_LICENSE_NUMBER`, `ERR_APPLICATION_ALREADY_ACTIVE`, `ERR_LIEN_ALREADY_EXISTS`, `ERR_CYCLE_WINDOW_OVERLAP`, `ERR_EMPTY_BATCH`, and `ERR_CYCLE_HAS_OPEN_APPLICATIONS` (HTTP 409); `ERR_CONTRACTOR_SUSPENDED` (HTTP 403); and `ERR_INSURANCE_INVALID`, `ERR_ZERO_SCOPE_AREA`, `ERR_PAYMENT_EXCEEDS_BALANCE`, and `ERR_APPROPRIATION_BELOW_OBLIGATIONS` (HTTP 422).
12. **Priority 11 — fiscal caps, always last.** `ERR_PROGRAM_CAP_EXCEEDED` (HTTP 402) and `ERR_PARCEL_LIFETIME_CAP_REACHED` (HTTP 422).

### 2.8. The Program Funds Identity

Each `ProgramCycle` is a self-contained ledger over three balances: `committed_cents`, `disbursed_cents`, and `available_cents`. After every mutation the identity must hold exactly: `appropriation_cents` equals the sum of `committed_cents`, `disbursed_cents`, and `available_cents`. Obligations move money from available to committed, reimbursements move it from committed to disbursed, and releases return it from committed to available; §3.1 and §3.6 pin each leg. There is no priority among approved applications by approval order — every capacity check is evaluated strictly at request time against the cycle's current balances, which already reflect every earlier obligation and release in request order.

## 3. Business Logic & Workflows

### 3.1. Funding Cycles and the Annual Appropriation

Each program year begins when a `ProgramCoordinator` opens a `ProgramCycle` carrying a `cycle_year` label, a `window_start_date` and `window_end_date` bracketing the application window, and an `appropriation_cents` funding cap that must be greater than zero. The window is a closed interval: `window_end_date` must fall strictly after `window_start_date`, and windows of different cycles may not overlap at all — one cycle's end date coinciding exactly with another's start date already counts as an overlap and is rejected with `ERR_CYCLE_WINDOW_OVERLAP`. At creation the cycle starts in `OPEN` status with `committed_cents` and `disbursed_cents` both zero, so `available_cents` equals the full appropriation.

Locking a cycle — the `OPEN → LOCKED` transition, performed by a coordinator — blocks new applications and new obligations while leaving in-flight obligated applications eligible for reimbursement; a lock attempted on a cycle not in `OPEN` fails with `ERR_INVALID_CYCLE_STATE`. While a cycle sits in `LOCKED` status, its balances continue to move as reimbursements and releases land. Closing a cycle — `LOCKED → CLOSED` — is permitted only once no application in the cycle remains in `SUBMITTED`, `RETURNED`, `APPROVED`, or `OBLIGATED` review status; otherwise the close fails with `ERR_CYCLE_HAS_OPEN_APPLICATIONS`. Both transitions increment the cycle's `version`.

A `FinanceOfficer` may adjust a live appropriation by a signed `delta_cents`, negative adjustments included, through the appropriation-adjustment write. Because the funds identity is invariant, a downward adjustment that would push `appropriation_cents` below the sum of `committed_cents` and `disbursed_cents` is rejected with `ERR_APPROPRIATION_BELOW_OBLIGATIONS`. This write participates in optimistic concurrency control exactly as §2.5 describes: the request must carry `expected_program_cycle_version` matching the cycle's current `version`, with mismatches failing as `ERR_STALE_CYCLE_VERSION`. A successful adjustment recomputes `available_cents` and increments the cycle's `version`.

### 3.2. Parcels, Segments, and the Condition Inventory

Program staff register the people and the pavement before any enforcement begins. A `ProgramCoordinator` registers each `PropertyOwner` with a `full_name`, a `mailing_address`, and an optional `hardship_tier` — one of `NONE`, `SENIOR_65`, or `LOW_INCOME`, defaulting to `NONE` — which represents a verified hardship classification and later influences both cost-share percentage and deadline length.

Parcels come next. A coordinator registers a `PropertyParcel` with its assessor `parcel_number` (unique across all parcels, with duplicates rejected as `ERR_DUPLICATE_PARCEL_NUMBER`), the `owner_id` of its current deeded owner, a `street_address`, a `street_class` of `LOCAL`, `COLLECTOR`, or `ARTERIAL`, and two optional booleans: `is_corner_lot`, recording frontage on two intersecting streets, and `is_city_owned`, both defaulting to false. At registration the ordinance determination lands automatically: `owner_responsibility_pct` is 0 for city-owned parcels — the city self-repairs and such parcels can never be noticed — and 100 for every other parcel, making the abutting owner fully responsible. The parcel's `delinquency_flag` starts false; it later reads true while any notice on the parcel sits in `DELINQUENT`, `CITY_REPAIR_SCHEDULED`, `CITY_REPAIR_COMPLETED`, or `LIENED` status, and is recomputed whenever a notice leaves that family. The parcel listing accepts an `owner_id` query filter returning a single owner's parcels.

From there an `Inspector` builds the sidewalk inventory. Each `SidewalkSegment` is registered against its abutting `parcel_id` with a unique `segment_code` (duplicates rejected as `ERR_DUPLICATE_SEGMENT_CODE`), a `length_ft` and `width_ft` that must each be greater than zero, and optional `is_corner_segment` and `has_existing_curb_ramp` booleans, both defaulting to false — the first marking that the segment includes a street-corner radius, the second that a compliant curb ramp is already present. A new segment starts `IN_SERVICE` with both condition indexes at zero. The segment listing accepts a `parcel_id` query filter.

Defect reporting is the inventory's engine. An `Inspector` records a `Defect` against a `segment_id`, supplying a `defect_type` of `VERTICAL_SEPARATION`, `HORIZONTAL_OPENING`, `SPALLING`, `SETTLEMENT`, `TREE_ROOT_UPHEAVAL`, or `CRUMBLED_JOINT`; an `area_sqft` greater than zero; and, for the three displacement types `VERTICAL_SEPARATION`, `HORIZONTAL_OPENING`, and `TREE_ROOT_UPHEAVAL`, a `measured_offset_inches` of zero or more. The optional `city_tree_involved` flag, defaulting to false, marks a city street tree as the suspected cause and routes the defect to urban forestry as §3.8 describes. The server stamps `recorded_by_inspector_id` with the acting inspector's `X-User-ID`; that stamp later anchors segregation of duties at inspection and verification time.

Classification is deterministic at creation. Severity weights for downstream scoring are 25 for `MINOR`, 60 for `MAJOR`, and 100 for `TRIP_HAZARD`, and the computed `severity_class` falls out of type-specific thresholds with inclusive lower bounds. For `VERTICAL_SEPARATION` and `TREE_ROOT_UPHEAVAL`, an offset of at least half an inch (0.50) is a `TRIP_HAZARD`, an offset of at least a quarter inch (0.25) but less than half an inch is `MAJOR`, and anything below a quarter inch is `MINOR`. A `HORIZONTAL_OPENING` of at least half an inch is `MAJOR`, otherwise `MINOR`. `SETTLEMENT` covering at least 9 square feet is `MAJOR`, otherwise `MINOR`. `SPALLING` and `CRUMBLED_JOINT` covering at least 16 square feet are `MAJOR`, otherwise `MINOR`. Offsets enter these comparisons exactly as recorded, per §2.6.

Each segment continuously maintains two computed condition views over its non-verified defects — those in `OPEN`, `AWAITING_FORESTRY`, or `UNDER_REPAIR` status. The screening view, `condition_screening`, is an integer equal to the highest severity weight present in that set: the worst defect dominates. The area-weighted view, `condition_area_weighted`, divides the sum of each defect's severity weight multiplied by its `area_sqft` by the sum of the `area_sqft` values, then rounds half-up to one decimal place. When no non-verified defects remain, both read zero. Both indexes, along with the segment's `open_defect_count` — the count of defects in those same three statuses — are recomputed whenever a defect is created, whenever a defect is verified, and whenever a defect returns to `OPEN` through an appeal reversal. The defect listing accepts `segment_id` and `status` query filters; each defect's forestry-review collection can be read through its nested listing, which contains at most one element.

A segment's lifecycle follows its defects automatically. The first defect recorded on an `IN_SERVICE` segment flags it (`IN_SERVICE → FLAGGED`). Issuing a notice covering one of its defects moves it from `FLAGGED` to `UNDER_NOTICE`. If that notice is later voided and no other active notice covers the segment, it falls back from `UNDER_NOTICE` to `FLAGGED`. When a batch award schedules city work whose notice covers the segment, it moves from `UNDER_NOTICE` to `REPAIR_IN_PROGRESS`. And whenever the `open_defect_count` reaches zero — whether through inspection sign-off from `UNDER_NOTICE`, through work verification from `REPAIR_IN_PROGRESS`, or directly from `FLAGGED` — the segment is `RESTORED`.

### 3.3. Notices to Repair: Issuance, Deadlines, and Delinquency

Enforcement begins when a `ProgramCoordinator` drafts a `RepairNotice` against a `parcel_id`, naming an ordered `defect_ids` list. Composition rules guard the draft, all at priority 7: the list must be non-empty (else `ERR_NO_ELIGIBLE_DEFECTS`); every listed defect must belong to a segment of the notice's parcel (else `ERR_DEFECT_NOT_IN_PARCEL`); no listed defect may already be covered by another non-terminal notice (else `ERR_DEFECT_UNDER_ACTIVE_NOTICE`); and the parcel must be noticable, meaning its `owner_responsibility_pct` is greater than zero — attempting to notice a city-owned parcel fails with `ERR_CITY_PARCEL_NOT_NOTICABLE`. An optional `base_deadline_days` sets the compliance window, defaulting to 45 days when omitted, and an optional `prior_notice_id` chains the draft to an earlier notice it re-issues; the referenced notice must be in `VOID` status on the same parcel, else the draft is rejected with `ERR_INVALID_NOTICE_REFERENCE`. A new notice starts as `DRAFT` with `appeal_status` set to `NONE`. The notice listing accepts `parcel_id`, `prior_notice_id`, and `status` query filters.

Issuing the notice — `DRAFT → ISSUED`, by a coordinator — requires every referenced defect to be in `OPEN` or `AWAITING_FORESTRY` status; any defect already `UNDER_REPAIR` or `VERIFIED` fails the issue with `ERR_INVALID_DEFECT_STATE`. At issuance the server stamps `issued_at` from the logical clock and `issued_by_user_id` from the coordinator's `X-User-ID`, then computes the `compliance_deadline`: the `issued_at` instant plus `base_deadline_days` days, extended by a further 30 days whenever the parcel's owner holds a `hardship_tier` other than `NONE`. Issuance cascades: every referenced defect in `OPEN` moves to `UNDER_REPAIR`, while defects still waiting on forestry remain `AWAITING_FORESTRY` until their review clears; and each referenced defect's segment moves from `FLAGGED` to `UNDER_NOTICE`.

A coordinator may extend an issued notice's deadline by `extra_days` through the extension write. This is the first OCC-guarded operation of §2.5: the request must carry `expected_notice_version` equal to the notice's current `version`, failing as `ERR_STALE_NOTICE_VERSION` when the client's view predates the latest mutation. Multiple sequential extensions are legitimate — each accepted extension adds its days to the `compliance_deadline` and increments the notice's `version`, so a stale client simply re-reads and retries.

Compliance is judged by inspection. An `Inspector` records an inspection against a notice with a `result` of `PASS` or `FAIL` and optional free-text `notes`, producing an immutable `InspectionRecord` stamped with the inspector's identity as `inspector_id` and the notice reference as `notice_id`; the record collection is readable through the notice's inspection listing. A passing inspection on a notice in `ISSUED` or `DELINQUENT` status — late compliance is accepted any time before city repair is scheduled — moves the notice to `COMPLIANT`, provided two segregation and safety gates hold: the inspecting officer's `X-User-ID` must differ from the `recorded_by_inspector_id` of every covered defect (else `ERR_SEGREGATION_OF_DUTIES`), and every covered defect must already be `UNDER_REPAIR`, since a defect still `AWAITING_FORESTRY` blocks sign-off with `ERR_FORESTRY_NOT_CLEARED`. On passage, each covered defect moves from `UNDER_REPAIR` to `VERIFIED`, every segment whose `open_defect_count` thereby reaches zero is `RESTORED`, and the parcel's `delinquency_flag` is recomputed.

Missing the deadline flips the notice to `DELINQUENT`. This happens two ways: a coordinator-run delinquency sweep advances every `ISSUED` notice whose `compliance_deadline` is strictly before the logical clock — equality still counts as compliant — and a failing inspection recorded while the clock is strictly past the deadline tips that notice over directly. Delinquency detonates a depth-three cascade. Every cost-share application on the notice in `SUBMITTED`, `RETURNED`, `APPROVED`, or `OBLIGATED` status is `CANCELLED`; each application cancelled out of `OBLIGATED` also flips its `payment_status` from `RESERVED` to `RELEASED` and returns its `provisional_award_cents` to the cycle by reducing `committed_cents`; the parcel's `delinquency_flag` turns true; and the notice's `version` increments. The sweep's second job, expiring stale approvals, is covered in §3.6; its response reports `swept_notice_count`, `expired_application_count`, `swept_notice_ids`, and `expired_application_ids`.

### 3.4. Appeals and Hearing Outcomes

An owner who disputes a notice appeals it — `ISSUED → UNDER_APPEAL` — supplying their `grounds`. Four preconditions guard the appeal, evaluated under the priority order of §2.7: the notice must be `ISSUED` (else `ERR_INVALID_NOTICE_STATE`); the acting owner must own the notice's parcel (else `ERR_OWNERSHIP_MISMATCH`); the logical clock must not be past the `compliance_deadline`, with an appeal landing exactly on the deadline still timely (else `ERR_APPEAL_WINDOW_CLOSED`); and the notice's `appeal_status` must be `NONE` or `UPHELD` — a `PENDING` appeal implies the notice is already under appeal and a `REVERSED` one implies it was voided, so any other combination fails with `ERR_APPEAL_ALREADY_PENDING`. A valid appeal sets `appeal_status` to `PENDING` and records the supplied text in `appeal_grounds`.

A `HearingOfficer` then decides the pending appeal, requiring the notice to be `UNDER_APPEAL` with `appeal_status` of `PENDING` (else `ERR_INVALID_NOTICE_STATE`) and — by segregation of duties — requiring the decider's `X-User-ID` to differ from the `issued_by_user_id` of the notice (else `ERR_SEGREGATION_OF_DUTIES`). Both branches stamp `appeal_decided_by_user_id` with the decider's identifier and `appeal_decided_at` from the logical clock, and both increment the notice's `version`.

The two outcomes diverge sharply. A `decision` of `UPHELD` returns the notice to `ISSUED`, sets `appeal_status` to `UPHELD`, and **replaces** the deadline: the new `compliance_deadline` is the decision instant plus 15 days, superseding rather than extending the prior deadline. The cycle is genuinely cyclic — a re-issued notice may be appealed again while the clock remains within its new deadline. A `decision` of `REVERSED` instead voids the notice (`UNDER_APPEAL → VOID`), sets `appeal_status` to `REVERSED`, releases every covered defect from `UNDER_REPAIR` back to `OPEN`, and returns each segment with no remaining `UNDER_REPAIR` defects from `UNDER_NOTICE` to `FLAGGED`. A voided notice can later be re-issued through a fresh draft chained by `prior_notice_id`, as §3.3 describes.

### 3.5. Cost-Share Applications and Award Mathematics

Once a notice is `ISSUED`, the parcel's owner may apply for cost-share by submitting a `CostShareApplication` naming the `notice_id`, the `parcel_id`, the target `cycle_id`, and an `estimated_qty_sqft` greater than zero declaring the repair scope. Composition checks run at priority 7 and state checks at priority 5: the referenced notice must be `ISSUED`; the cycle must be `OPEN` (else `ERR_CYCLE_NOT_OPEN`); the application's `parcel_id` must equal the notice's parcel (else `ERR_PARCEL_NOTICE_MISMATCH`); the acting owner must own that parcel; and the notice may carry at most one application in a non-terminal review status at a time (else `ERR_APPLICATION_ALREADY_ACTIVE`). At creation the server copies `owner_id` from the parcel, sets `review_status` to `SUBMITTED` and `payment_status` to `UNFUNDED`, computes the accessibility flag and the award figures below, and leaves `final_award_cents` null until reimbursement. The application listing accepts `notice_id`, `parcel_id`, `owner_id`, and `cycle_id` filters in combination.

The city's share percentage, `share_pct`, combines three components and caps the result. The base city share is 50 percent. Street classification adds 20 points for an `ARTERIAL` parcel, 10 for a `COLLECTOR`, and nothing for a `LOCAL`. Hardship adds 30 points for a `LOW_INCOME` owner, 20 for `SENIOR_65`, and nothing for `NONE`. The percentage is the sum of the three components, capped at 90 — so a low-income owner on an arterial fronts only 10 percent of the shared cost.

Accessibility drives a parallel flag. `ramp_upgrade_required` reads true exactly when at least one defect covered by the notice sits on a segment whose `is_corner_segment` is true and whose `has_existing_curb_ramp` is false — a corner repair without an existing ramp must bring the corner up to standard.

The provisional award then proceeds in a pinned order, with per-component rounding half-up to whole cents. First, the repair estimate is the declared `estimated_qty_sqft` multiplied by the city engineer unit rate of 1,200 cents per square foot — twelve dollars — rounded half-up. Second, the ramp allowance is a flat 250,000 cents (2,500 dollars) when `ramp_upgrade_required` holds, and zero otherwise. Third, the city repair share is the repair estimate multiplied by `share_pct` and divided by 100, rounded half-up. Fourth, the uncapped award is the city repair share plus the ramp allowance. Fifth, the parcel's lifetime remaining allowance is 800,000 cents (8,000 dollars) minus everything the parcel has already absorbed: the sum of `provisional_award_cents` over the parcel's applications in `APPROVED` or `OBLIGATED` status, plus the sum of `final_award_cents` over its `REIMBURSED` applications. When that remainder is zero or negative, creation fails outright with `ERR_PARCEL_LIFETIME_CAP_REACHED`. Finally, `provisional_award_cents` is the smallest of the 400,000-cent (4,000-dollar) per-application cap, the uncapped award, and the lifetime remainder. This engineer-estimate variant is deliberately forward-looking: it uses the flat engineer rate regardless of what the actual repair later costs, which is precisely where the actual-invoice variant of §3.6 diverges.

Review lands through a coordinator's decision with an `outcome` of `APPROVE`, `DENY`, or `RETURN`, optionally annotated with a `reviewer_note`; any decision attempted on an application not in `SUBMITTED` fails with `ERR_INVALID_APPLICATION_STATE`. Approval moves the application to `APPROVED` and stamps `approved_at` from the logical clock, with `approval_expires_at` computed as the approval instant plus 60 days — obligation after that instant fails. Denial terminates the application as `DENIED`; return moves it to `RETURNED`, from which the owning owner may resubmit it to `SUBMITTED` — a revision cycle that may repeat without bound. The owner may also withdraw from any of `SUBMITTED`, `RETURNED`, `APPROVED`, or `OBLIGATED`, terminating the application as `WITHDRAWN`; withdrawal from `OBLIGATED` additionally flips `payment_status` from `RESERVED` to `RELEASED` and subtracts the `provisional_award_cents` from the cycle's `committed_cents`, incrementing both the application's and the cycle's `version`. Withdrawal and resubmission from a state the application does not occupy, or by anyone but the owning owner, fail with `ERR_INVALID_APPLICATION_STATE` and `ERR_OWNERSHIP_MISMATCH` respectively.

### 3.6. Obligation, Reimbursement, and Fund Movement

Approval alone spends nothing; a `FinanceOfficer` must obligate the award — `APPROVED → OBLIGATED` — which reserves the provisional amount against the cycle. Obligation checks, in the priority order of §2.7: the application must be `APPROVED`; the cycle must still be `OPEN` (else `ERR_CYCLE_NOT_OPEN`); the logical clock must be no later than `approval_expires_at`, with an obligation exactly at expiry still timely (else `ERR_APPLICATION_EXPIRED`); and the fiscal cap, evaluated last and at request time against the cycle's current balances, requires the sum of `committed_cents` and this application's `provisional_award_cents` not to exceed `appropriation_cents` — equality is allowed — else `ERR_PROGRAM_CAP_EXCEEDED`. A successful obligation moves `payment_status` from `UNFUNDED` to `RESERVED`, adds the provisional award to the cycle's `committed_cents`, recomputes `available_cents`, and increments both entities' versions.

Approved applications are not immortal. The delinquency sweep of §3.3 also expires every `APPROVED` application whose `approval_expires_at` is strictly before the logical clock, moving it to `EXPIRED` without touching cycle funds, since nothing was reserved yet.

Reimbursement — `OBLIGATED → REIMBURSED`, again by a `FinanceOfficer` — settles the award against actuals. The application must be `OBLIGATED`, and the source notice must have reached `COMPLIANT` (else `ERR_NOTICE_NOT_COMPLIANT`). The officer supplies the `final_repair_cost_cents` from the owner's invoice and, when the accessibility flag was set, a `ramp_receipt_cents`; supplying a nonzero ramp receipt for an application whose `ramp_upgrade_required` is false is rejected with `ERR_INVALID_REQUEST`. The final award mirrors the provisional order with the actual-invoice variant's substitutions: the repair part is `final_repair_cost_cents` multiplied by `share_pct` and divided by 100, rounded half-up; the ramp part is the lesser of `ramp_receipt_cents` and the 250,000-cent flat allowance when a ramp upgrade was required, and zero otherwise; the uncapped award is their sum; the parcel lifetime remainder is recomputed as in §3.5 but at reimbursement time; and `final_award_cents` is the smallest of the 400,000-cent per-application cap, the uncapped award, and that remainder. The cycle cap is then re-examined in its reimbursement form: `committed_cents` minus this application's `provisional_award_cents`, plus `disbursed_cents`, plus `final_award_cents`, must not exceed `appropriation_cents`, else `ERR_PROGRAM_CAP_EXCEEDED`. On success the reservation unwinds — `committed_cents` drops by the provisional award while `disbursed_cents` grows by the final award — `payment_status` moves from `RESERVED` to `DISBURSED`, and both the application's and the cycle's `version` increment.

### 3.7. Neighborhood Bid Pooling and Contractor Selection

When notices go delinquent, the city repairs the walk itself and pools the work for pricing leverage. A `ProgramCoordinator` opens a `BidBatch` with a `neighborhood_code`, a half-open work window from `work_window_start` to `work_window_end` — the end being the day after the last permitted work day, and required to fall strictly after the start — and a `bid_deadline`. New batches start `OPEN_FOR_ITEMS` with `estimated_total_cents` at zero. The batch listing accepts `awarded_bid_id` and `neighborhood_code` filters, the former locating the batch a given bid won.

Work enters the pool item by item. A coordinator creates a `BatchWorkItem` naming a `batch_id`, a `notice_id`, a `scope_sqft` greater than zero, and an `engineer_unit_rate_cents` greater than zero. The referenced notice must be `DELINQUENT` — pooling is the city-repair path — and must not already have a work item in `POOLED`, `SCHEDULED`, `WORK_COMPLETED`, or `VERIFIED` status in any batch (else `ERR_NOTICE_ALREADY_POOLED`). Each item's `includes_ramp_upgrade` is computed by the same accessibility trigger as applications, evaluated over the notice's covered defect set. The batch's `estimated_total_cents` is recomputed on every item addition and removal as the sum, over the batch's pooled items, of each item's `scope_sqft` multiplied by its `engineer_unit_rate_cents` and rounded half-up per item before summing; removed items drop out of the figure, while items scheduled by award remain counted until verified or removed, so the estimate stays frozen while the batch is sealed. The work-item listing filters by `batch_id` or `notice_id`. While the batch remains `OPEN_FOR_ITEMS`, a coordinator may remove an item — `POOLED → REMOVED`, failing with `ERR_INVALID_WORK_ITEM_STATE` or `ERR_INVALID_BATCH_STATE` outside those states — which recomputes the estimate and increments both the item's and the batch's `version`.

Sealing the batch — `OPEN_FOR_ITEMS → SEALED_FOR_BIDDING` — requires at least one `POOLED` item (else `ERR_EMPTY_BATCH`) and enforces the forestry cure buffer: for every pooled item, every forestry review covering that item's notice defects that has reached `CLEARED` with a recorded `work_completed_at` must have finished root work at least 7 days before `work_window_start`; a tighter gap fails the seal with `ERR_CURE_WINDOW_VIOLATION`.

Bidding is contractor business. A `ProgramCoordinator` first registers each `Contractor` with a `company_name`, a `license_number` unique across contractors (duplicates rejected as `ERR_DUPLICATE_LICENSE_NUMBER`, and serving later as the final award tie-break in ascending order), and an `insurance_valid_until` date; new contractors start with `is_suspended` false. A suspension flips that flag true, after which the contractor's bids are rejected with `ERR_CONTRACTOR_SUSPENDED` and it is excluded from award eligibility. A `Contractor` submits a bid on a sealed batch by naming the `batch_id`, a `unit_rate_cents` greater than zero, a `ramp_flat_fee_cents` of zero or more, and — per §2.5 — an `expected_batch_version` matching the batch's current `version`, with mismatches rejected as `ERR_STALE_BATCH_VERSION`. Bids are accepted only while the batch is `SEALED_FOR_BIDDING` (else `ERR_INVALID_BATCH_STATE`) and only while the logical clock has not passed the `bid_deadline`, with a bid landing exactly at the deadline still timely (else `ERR_BID_DEADLINE_PASSED`); the bidder's insurance must also cover the entire work window at submission, failing as `ERR_INSURANCE_INVALID` when `insurance_valid_until` falls before `work_window_end`. The server stamps `contractor_id` from the bidder's `X-User-ID` and `submitted_at` from the logical clock, snapshots `evaluated_total_cents`, and increments the batch's `version`. A contractor holds at most one live bid per batch: a second submission by the same contractor on the same batch moves the prior `SUBMITTED` bid to `SUPERSEDED`, leaving only the newest bid award-eligible. A bidder may also withdraw a `SUBMITTED` bid while the batch remains sealed, provided the bid is its own — `SUBMITTED → WITHDRAWN`, failing with `ERR_INVALID_BID_STATE`, `ERR_OWNERSHIP_MISMATCH`, or `ERR_INVALID_BATCH_STATE` otherwise. The bid listing filters by `batch_id` or `contractor_id`.

Award — `SEALED_FOR_BIDDING → AWARDED` by a coordinator — is the system's deepest cascade. The logical clock must be strictly past the `bid_deadline` (else `ERR_BID_WINDOW_STILL_OPEN`). The forestry gate then requires every review on every pooled item's notice defects to be `CLEARED` (else `ERR_FORESTRY_NOT_CLEARED`). The selector recomputes each bid's `evaluated_total_cents` as its `unit_rate_cents` multiplied by the batch's total pooled scope in square feet, plus its `ramp_flat_fee_cents` multiplied by the count of pooled items flagged for ramp upgrade — the same formula snapshotted at submission. A bid is eligible only when all four conditions hold: its status is `SUBMITTED`; its contractor is not suspended; the contractor's `insurance_valid_until` reaches at least `work_window_end`; and the contractor holds no conflicting window — for every other batch that contractor has in `AWARDED` or `WORK_IN_PROGRESS`, the half-open windows must not intersect, where an existing window ending exactly at this batch's start does not conflict. Eligible bids rank by `evaluated_total_cents` ascending, ties broken by earlier `submitted_at`, further ties by ascending contractor `license_number`; an empty eligible pool fails the award with `ERR_NO_ELIGIBLE_BIDS`. The winning bid moves from `SUBMITTED` to `AWARDED` with its `evaluated_total_cents` frozen into the batch's `awarded_total_cents` and its `id` recorded as `awarded_bid_id`; every other `SUBMITTED` bid becomes `NOT_AWARDED`. The cascade continues downward: each `POOLED` work item becomes `SCHEDULED`; each pooled notice moves from `DELINQUENT` to `CITY_REPAIR_SCHEDULED`; and the segments of the referenced defects move to `REPAIR_IN_PROGRESS`.

Work may begin — `AWARDED → WORK_IN_PROGRESS` — once the logical clock reaches `work_window_start`, with the first day itself eligible and anything earlier failing as `ERR_WORK_WINDOW_NOT_REACHED`. The awarded contractor then reports each item complete — `SCHEDULED → WORK_COMPLETED` — a write accepted only while the batch is `WORK_IN_PROGRESS` and only from the contractor whose `id` matches the awarded bid's `contractor_id` (else `ERR_OWNERSHIP_MISMATCH`). Verification closes the loop: an `Inspector` verifies each completed item — `WORK_COMPLETED → VERIFIED` — subject to the same segregation rule as compliance inspections, so the verifier's `X-User-ID` must differ from the `recorded_by_inspector_id` of every defect on the item's notice (else `ERR_SEGREGATION_OF_DUTIES`). Verification cascades outward: every defect of the item's notice moves from `UNDER_REPAIR` to `VERIFIED`; segments whose `open_defect_count` reaches zero are `RESTORED`; when every item of a notice is verified, that notice moves from `CITY_REPAIR_SCHEDULED` to `CITY_REPAIR_COMPLETED`; and when every item of the batch is verified, the batch itself moves from `WORK_IN_PROGRESS` to `COMPLETED` — the parent's state derived entirely from its children.

Cancellation is the escape hatch before award. Cancelling a batch in `OPEN_FOR_ITEMS` or `SEALED_FOR_BIDDING` — anything later fails with `ERR_INVALID_BATCH_STATE` — moves every `POOLED` item to `REMOVED` while leaving the referenced notices `DELINQUENT`; cancelling a sealed batch additionally moves every `SUBMITTED` bid to `NOT_AWARDED`.

### 3.8. Urban Forestry Coordination and the Cure Buffer

Tree-root damage gets a dedicated review loop because the city cannot bill owners for conflicts its own trees caused. When an inspector records a `TREE_ROOT_UPHEAVAL` defect with `city_tree_involved` set, the defect lands directly in `AWAITING_FORESTRY` rather than `OPEN` — `OPEN` is the initial state only for non-forestry defects — and a `ForestryReview` is auto-created against that `defect_id` in `PENDING` status.

A `ForestryOfficer` disposes of the review in one of two shapes. A `decision` of `PRUNE_APPROVED` or `REMOVAL_ORDERED` moves the review from `PENDING` to `DECIDED`, stamping `decision` and `decided_by_user_id`; physical root work must still follow, and the officer later clears the review — `DECIDED → CLEARED` — which stamps `work_completed_at` from the logical clock. A `decision` of `NO_CITY_CONFLICT` instead clears the review immediately, `PENDING → CLEARED`, with `work_completed_at` staying null. Decisions or clears attempted on a review not in the required source state fail with `ERR_INVALID_FORESTRY_STATE`. Either way, clearing frees the linked defect: it moves from `AWAITING_FORESTRY` to `UNDER_REPAIR` when a non-terminal notice already references it — its repair was noticed while root work was pending — and back to `OPEN` otherwise, ready to be drafted onto a future notice.

Forestry status then gates two later milestones, as §3.3 and §3.7 detail: the 7-day cure buffer between recorded root-work completion and the batch's `work_window_start` is enforced at seal time, and a full `CLEARED` sweep of every covered review is enforced again at award time, with the seal-time gap failure reported as `ERR_CURE_WINDOW_VIOLATION` and the award-time gate as `ERR_FORESTRY_NOT_CLEARED`.

### 3.9. Liens, Interest, and Foreclosure

City-completed repairs convert to cost recovery. Once a notice reaches `CITY_REPAIR_COMPLETED`, a `FinanceOfficer` assesses a `LienCase` against its `notice_id`, supplying the city's `actual_repair_cost_cents` contractor invoice — greater than zero — and optionally an `interest_rate_bp` defaulting to 800 basis points, an eight percent annual simple rate. The notice may carry at most one lien in a non-terminal status (else `ERR_LIEN_ALREADY_EXISTS`); the new lien copies `parcel_id` from its notice, starts in `ASSESSED` status, stamps `assessed_at` from the logical clock as day zero for accrual, and flips the notice from `CITY_REPAIR_COMPLETED` to `LIENED`.

Assessment arithmetic runs in pinned order. The administrative fee, `admin_fee_cents`, is the greater of 15,000 cents (150 dollars) and ten percent of the actual repair cost rounded half-up. The city-tree credit isolates city-caused damage: `city_caused` area is the sum of `area_sqft` over the notice's defects that are `TREE_ROOT_UPHEAVAL` with `city_tree_involved` set and whose forestry review was decided `PRUNE_APPROVED` or `REMOVAL_ORDERED`; the total scope area is the sum of `area_sqft` over every defect the notice covers, and a zero total aborts the assessment with `ERR_ZERO_SCOPE_AREA`. The credit, `city_credit_cents`, multiplies the actual repair cost by the city-caused area first, then divides by the total scope area, then rounds half-up — multiply, divide, round, in that order. The owner's principal, `owner_principal_cents`, is the actual repair cost minus the city credit plus the administrative fee. Bookkeeping initializes `principal_remaining_cents` to the owner principal, `accrued_interest_cents` to zero, and `last_accrual_day` to zero. The lien listing filters by `notice_id` or `parcel_id`.

Recording — `ASSESSED → RECORDED` by a finance officer — makes the lien payable; other transitions out of their source states fail with `ERR_INVALID_LIEN_STATE`. From `RECORDED` or `PARTIALLY_PAID`, the owning owner posts payments of `amount_cents`, which must be greater than zero (else `ERR_INVALID_REQUEST`) and may not exceed the outstanding balance including interest accrued through the payment date (else `ERR_PAYMENT_EXCEEDS_BALANCE`). Each payment event runs the accrual in pinned order, with whole days counted between dates and the assessment date as day zero. First, the interest due is the `principal_remaining_cents` multiplied by `interest_rate_bp`, multiplied by the days elapsed since `last_accrual_day`, divided by 3,650,000 — the 365-day year scaled for basis points — rounded half-up. Second, that interest is added to `accrued_interest_cents` and `last_accrual_day` advances to the payment day. Third, the payment applies interest-first: it extinguishes the accrued interest balance, and only any remainder reduces `principal_remaining_cents`. Fourth, `outstanding_balance_cents` restates as the sum of `principal_remaining_cents` and `accrued_interest_cents`. Per-event rounding and interest-first application are the pinned behavior; a single end-to-end computation or principal-first application yields different cents and is non-conformant. A payment leaving a positive balance lands the lien in `PARTIALLY_PAID`, where further payments repeat the same cycle; a payment covering the full outstanding amount satisfies the lien — `RECORDED` or `PARTIALLY_PAID → SATISFIED` — which cascades the notice from `LIENED` to `CLOSED` and recomputes the parcel's `delinquency_flag`.

Reads of a lien come in two variants. The statement variant, returned by the standard lien read, reports `accrued_interest_cents` as stored plus interest projected through the current logical clock day. The payoff-quote variant projects further: its response carries `principal_remaining_cents`, `accrued_interest_cents`, a `projected_interest_cents` computed through the current clock day plus 15 days, the resulting `good_through_date`, and their total as `payoff_total_cents` — so whenever principal remains, the payoff quote exceeds the same-day statement balance.

When recovery stalls, a `FinanceOfficer` refers the lien to foreclosure — `RECORDED` or `PARTIALLY_PAID → FORECLOSURE_REFERRED` — permitted only once the logical clock has reached at least 90 days after `assessed_at` (earlier attempts fail with `ERR_FORECLOSURE_TOO_EARLY`) and only while the outstanding balance including accrued interest remains positive. `SATISFIED` and `FORECLOSURE_REFERRED` are the lien's terminal states; the program's enforcement arc — notice, delinquency, city repair, lien, and either satisfaction or referral — is then complete.

## 4. Endpoint Definitions

Creation of a new resource returns HTTP 201; state transitions, modifications, and all reads return HTTP 200. The table below is a summary only — request fields, computation rules, and cascade behavior are specified in §2 and §3, and the complete error vocabulary in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the logical clock (startup default `2026-08-01T00:00:00Z`; never wall-clock) | ProgramCoordinator |
| POST | `/program-cycles` | Create a funding cycle; windows disjoint under closed-interval semantics | ProgramCoordinator |
| GET | `/program-cycles/{id}` | Read one cycle including committed/disbursed/available balances | All seven roles |
| POST | `/program-cycles/{id}/lock` | Lock the cycle: `OPEN → LOCKED` | ProgramCoordinator |
| POST | `/program-cycles/{id}/close` | Close the cycle: `LOCKED → CLOSED`; requires no in-flight applications | ProgramCoordinator |
| POST | `/program-cycles/{id}/appropriation-adjustments` | Adjust appropriation by a signed delta; OCC on cycle version | FinanceOfficer |
| POST | `/property-owners` | Register a property owner with verified hardship tier | ProgramCoordinator |
| GET | `/property-owners/{id}` | Read one property owner | All seven roles |
| POST | `/parcels` | Register a parcel; ordinance responsibility computed | ProgramCoordinator |
| GET | `/parcels` | List parcels; optional owner filter | All seven roles |
| GET | `/parcels/{id}` | Read one parcel | All seven roles |
| POST | `/segments` | Register a sidewalk segment in the condition inventory | Inspector |
| GET | `/segments` | List segments; optional parcel filter | All seven roles |
| GET | `/segments/{id}` | Read one segment | All seven roles |
| POST | `/defects` | Record and classify a defect; city-tree root upheavals auto-route to forestry | Inspector |
| GET | `/defects` | List defects; optional segment and status filters | All seven roles |
| GET | `/defects/{id}` | Read one defect | All seven roles |
| GET | `/defects/{id}/forestry-reviews` | List forestry reviews for one defect | All seven roles |
| POST | `/repair-notices` | Create a `DRAFT` notice covering eligible defects of one parcel | ProgramCoordinator |
| GET | `/repair-notices` | List notices; filter by parcel, prior notice, or status | All seven roles |
| GET | `/repair-notices/{id}` | Read one notice | All seven roles |
| POST | `/repair-notices/{id}/issue` | Issue the notice: `DRAFT → ISSUED`; computes the deadline | ProgramCoordinator |
| POST | `/repair-notices/{id}/extensions` | Extend the compliance deadline; OCC on notice version | ProgramCoordinator |
| POST | `/repair-notices/{id}/appeal` | Appeal an issued notice: `ISSUED → UNDER_APPEAL` | PropertyOwner |
| POST | `/repair-notices/{id}/appeal-decision` | Decide a pending appeal; `UPHELD` re-issues, `REVERSED` voids | HearingOfficer |
| POST | `/repair-notices/{id}/inspections` | Record a compliance inspection; `PASS` complies, late `FAIL` delinquents | Inspector |
| GET | `/repair-notices/{id}/inspections` | List inspection records of one notice | All seven roles |
| POST | `/cost-share-applications` | Apply for cost-share against an issued notice in an open cycle | PropertyOwner |
| GET | `/cost-share-applications` | List applications; filters combinable | All seven roles |
| GET | `/cost-share-applications/{id}` | Read one application | All seven roles |
| POST | `/cost-share-applications/{id}/decision` | Coordinator decision: `APPROVE`, `DENY`, or `RETURN` | ProgramCoordinator |
| POST | `/cost-share-applications/{id}/resubmit` | Resubmit a returned application | PropertyOwner |
| POST | `/cost-share-applications/{id}/obligate` | Obligate an approved award against the cycle cap | FinanceOfficer |
| POST | `/cost-share-applications/{id}/withdraw` | Withdraw; from `OBLIGATED` also releases the reservation | PropertyOwner |
| POST | `/cost-share-applications/{id}/reimburse` | Reimburse against actual invoice after notice compliance | FinanceOfficer |
| POST | `/bid-batches` | Create a neighborhood bid batch | ProgramCoordinator |
| GET | `/bid-batches` | List batches; filter by awarded bid or neighborhood | All seven roles |
| GET | `/bid-batches/{id}` | Read one batch | All seven roles |
| POST | `/bid-batches/{id}/seal` | Seal for bidding; enforces non-empty pool and forestry cure buffer | ProgramCoordinator |
| POST | `/bid-batches/{id}/award` | Award after the bid deadline; cascades to bids, items, notices, segments | ProgramCoordinator |
| POST | `/bid-batches/{id}/start-work` | Begin work once the window opens | ProgramCoordinator |
| POST | `/bid-batches/{id}/cancel` | Cancel before award; items removed, bids not awarded | ProgramCoordinator |
| POST | `/batch-work-items` | Pool a delinquent notice into an open batch | ProgramCoordinator |
| GET | `/batch-work-items` | List work items; filter by batch or notice | All seven roles |
| GET | `/batch-work-items/{id}` | Read one work item | All seven roles |
| POST | `/batch-work-items/{id}/remove` | Remove a pooled item while the batch is open | ProgramCoordinator |
| POST | `/batch-work-items/{id}/complete` | Awarded contractor marks scheduled work complete | Contractor |
| POST | `/batch-work-items/{id}/verify` | Inspector verifies completed work; cascades to notice and batch | Inspector |
| POST | `/contractors` | Register a contractor with license and insurance validity | ProgramCoordinator |
| GET | `/contractors` | List contractors | All seven roles |
| POST | `/contractors/{id}/suspend` | Suspend a contractor from bidding and award eligibility | ProgramCoordinator |
| POST | `/bids` | Submit a bid on a sealed batch; resubmission supersedes; OCC on batch version | Contractor |
| GET | `/bids` | List bids; filter by batch or contractor | All seven roles |
| GET | `/bids/{id}` | Read one bid | All seven roles |
| POST | `/bids/{id}/withdraw` | Withdraw a submitted bid while the batch is sealed | Contractor |
| POST | `/forestry-reviews/{id}/decision` | Decide a pending review; `NO_CITY_CONFLICT` clears immediately | ForestryOfficer |
| POST | `/forestry-reviews/{id}/clear` | Clear a decided review after root work; frees the defect | ForestryOfficer |
| POST | `/lien-cases` | Assess a lien on a city-completed notice; notice becomes `LIENED` | FinanceOfficer |
| GET | `/lien-cases` | List liens; filter by notice or parcel | All seven roles |
| GET | `/lien-cases/{id}` | Read one lien; interest fields use the statement variant | All seven roles |
| GET | `/lien-cases/{id}/payoff-quote` | Payoff variant; interest projected through current day plus 15 days | All seven roles |
| POST | `/lien-cases/{id}/record` | Record an assessed lien: `ASSESSED → RECORDED` | FinanceOfficer |
| POST | `/lien-cases/{id}/payments` | Apply an owner payment; per-event accrual, interest-first waterfall | PropertyOwner |
| POST | `/lien-cases/{id}/foreclosure-referral` | Refer to foreclosure after 90 days with a positive balance | FinanceOfficer |
| POST | `/delinquency-sweeps` | Sweep past-deadline notices to delinquent and expire stale approvals | ProgramCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error are specified where the corresponding rule lives in §2 and §3; this table is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_OWNERSHIP_MISMATCH` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_PROGRAM_CYCLE_NOT_FOUND` | 404 |
| `ERR_PROPERTY_OWNER_NOT_FOUND` | 404 |
| `ERR_PARCEL_NOT_FOUND` | 404 |
| `ERR_SEGMENT_NOT_FOUND` | 404 |
| `ERR_DEFECT_NOT_FOUND` | 404 |
| `ERR_REPAIR_NOTICE_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_BID_BATCH_NOT_FOUND` | 404 |
| `ERR_WORK_ITEM_NOT_FOUND` | 404 |
| `ERR_CONTRACTOR_NOT_FOUND` | 404 |
| `ERR_BID_NOT_FOUND` | 404 |
| `ERR_FORESTRY_REVIEW_NOT_FOUND` | 404 |
| `ERR_LIEN_CASE_NOT_FOUND` | 404 |
| `ERR_INVALID_CYCLE_STATE` | 409 |
| `ERR_CYCLE_NOT_OPEN` | 409 |
| `ERR_INVALID_NOTICE_STATE` | 409 |
| `ERR_INVALID_DEFECT_STATE` | 409 |
| `ERR_INVALID_APPLICATION_STATE` | 409 |
| `ERR_INVALID_BATCH_STATE` | 409 |
| `ERR_INVALID_WORK_ITEM_STATE` | 409 |
| `ERR_INVALID_BID_STATE` | 409 |
| `ERR_INVALID_FORESTRY_STATE` | 409 |
| `ERR_INVALID_LIEN_STATE` | 409 |
| `ERR_NOTICE_NOT_COMPLIANT` | 409 |
| `ERR_STALE_NOTICE_VERSION` | 412 |
| `ERR_STALE_BATCH_VERSION` | 412 |
| `ERR_STALE_CYCLE_VERSION` | 412 |
| `ERR_DEFECT_NOT_IN_PARCEL` | 422 |
| `ERR_DEFECT_UNDER_ACTIVE_NOTICE` | 422 |
| `ERR_NO_ELIGIBLE_DEFECTS` | 422 |
| `ERR_CITY_PARCEL_NOT_NOTICABLE` | 422 |
| `ERR_NOTICE_ALREADY_POOLED` | 422 |
| `ERR_INVALID_NOTICE_REFERENCE` | 422 |
| `ERR_PARCEL_NOTICE_MISMATCH` | 422 |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 |
| `ERR_BID_DEADLINE_PASSED` | 422 |
| `ERR_BID_WINDOW_STILL_OPEN` | 422 |
| `ERR_WORK_WINDOW_NOT_REACHED` | 422 |
| `ERR_APPLICATION_EXPIRED` | 422 |
| `ERR_FORECLOSURE_TOO_EARLY` | 422 |
| `ERR_DUPLICATE_PARCEL_NUMBER` | 409 |
| `ERR_DUPLICATE_SEGMENT_CODE` | 409 |
| `ERR_DUPLICATE_LICENSE_NUMBER` | 409 |
| `ERR_APPLICATION_ALREADY_ACTIVE` | 409 |
| `ERR_LIEN_ALREADY_EXISTS` | 409 |
| `ERR_CYCLE_WINDOW_OVERLAP` | 409 |
| `ERR_CONTRACTOR_SUSPENDED` | 403 |
| `ERR_INSURANCE_INVALID` | 422 |
| `ERR_EMPTY_BATCH` | 409 |
| `ERR_ZERO_SCOPE_AREA` | 422 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_APPROPRIATION_BELOW_OBLIGATIONS` | 422 |
| `ERR_CYCLE_HAS_OPEN_APPLICATIONS` | 409 |
| `ERR_PROGRAM_CAP_EXCEEDED` | 402 |
| `ERR_PARCEL_LIFETIME_CAP_REACHED` | 422 |
| `ERR_NO_ELIGIBLE_BIDS` | 422 |
| `ERR_FORESTRY_NOT_CLEARED` | 409 |
| `ERR_CURE_WINDOW_VIOLATION` | 422 |
