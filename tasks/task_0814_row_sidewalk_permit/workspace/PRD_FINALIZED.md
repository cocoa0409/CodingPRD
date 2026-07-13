# Row Sidewalk Permit API — Product Requirements Document

## 1. Introduction

Municipal right-of-way management sits at the intersection of public safety, fiscal accountability, and physical infrastructure protection. Contractors who occupy a roadway lane, close a full street, or obstruct a sidewalk must be permitted, bonded, inspected, and — when they fail to restore the ground they disturbed — penalized. This document specifies the Right-of-Way & Sidewalk Obstruction Permit API, the system of record that governs an occupancy permit from its first draft through review, issuance, active occupancy, restoration inspection, and final close-out or expiration.

The API models a central **Permit** aggregate that carries a lifecycle of its own and owns a family of child records: a traffic-control plan, a restoration bond, one or more lane closures, sidewalk obstructions, encroachment agreements, and violation notices. Alongside the aggregate live flat reference resources — the **Applicant** who holds the permit, the **StreetSegment** whose zoning class drives fee rates and utility-cut moratoria, and the **SidewalkSpan** whose ADA clearance constrains obstructions. The system enforces compliance at every gate: a permit cannot be issued without an approved traffic-control plan and a sufficient restoration bond, the reviewer who approved a permit cannot be the person who issues it, a fresh pavement cut cannot violate a repaving moratorium, and a permittee who accumulates enough penalties has the permit revoked with all downstream occupancy voided and its bond forfeited.

Because permit occupancy is inherently time-bound, the system runs on a server-controlled logical clock rather than wall-clock time, so that occupancy durations, moratorium windows, and expiration boundaries are deterministic and testable. Fees, surcharges, penalties, and bond refunds are all computed in integer cents under fixed rounding rules.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply to every endpoint. All resources are mounted at the API root.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation — or an `Applicant` attempts to act on a permit it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles: `Applicant`, `PermitReviewer`, `Inspector`, `EnforcementOfficer`, and `PlatformAdmin`.

The `Applicant` role is **entity-backed**: when `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant` record. Ownership checks on any resource that references an applicant compare the governing permit's `applicant_id` to `X-User-ID`; a mismatch is an authorization failure. At permit-creation time this same rule requires the submitted `applicant_id` to equal `X-User-ID`, so an applicant may only create permits it will own.

The remaining four roles are **opaque operator identifiers** not tied to any persisted entity. When `X-User-Role` is `PermitReviewer`, `Inspector`, `EnforcementOfficer`, or `PlatformAdmin`, `X-User-ID` is an operator identifier that the server does not compare against any entity's `id`. The server may nonetheless record such an identifier where a transition captures it: a reviewer's `X-User-ID` is stored as `assigned_reviewer_user_id` on a permit when they approve it, and an inspector's `X-User-ID` is stored as `inspector_user_id` on a lane closure when they sign off its restoration.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by the resource's `created_at` timestamp in ascending order. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits at the moment of creation. Most resources additionally carry an `updated_at` timestamp — an ISO 8601 UTC value refreshed on every mutation — and a `version` integer that begins at 1 and increments by one on every mutation. These version and modification-time semantics apply to the `Applicant`, `StreetSegment`, `SidewalkSpan`, `Permit`, `TrafficControlPlan`, `RestorationBond`, `LaneClosure`, `SidewalkObstruction`, and `EncroachmentAgreement` resources.

The `ViolationNotice` resource is the sole exception: it is immutable after creation and therefore carries only `id` and `created_at`. It has no `updated_at` field and no `version` field.

Whenever a mutation updates a resource — including a change to a purely derived field such as a permit's `cumulative_penalty_cents` or a segment's `active_lane_closure_count`, or a cascade the server applies without a direct client request on that resource — the affected resource's `updated_at` is refreshed and its `version` is incremented.

### 2.5. Fee Precision, Rounding, and Monetary Fields

Every monetary quantity in the system is stored and returned as an integer number of cents; there are no fractional cents and no floating-point currency in responses. Fields carrying money include the permit's `estimated_fee_cents`, `final_fee_cents`, `surcharge_cents`, `total_charge_cents`, and `cumulative_penalty_cents`; the bond's `posted_cents`, `required_cents`, `held_cents`, `refunded_cents`, `forfeited_cents`, and `provisional_refund_cents`; the closure's `estimated_deficiency_cents` and `assessed_deficiency_cents`; the violation's `penalty_cents`; and the encroachment agreement's `proposed_fee_cents` and `agreed_fee_cents`.

Wherever a calculation multiplies to produce a non-integer intermediate — an occupancy fee's daily-rate product, a per-component surcharge, or an escalated penalty — the result is rounded to the nearest whole cent using the round-half-up rule (a value ending in exactly one-half cent rounds up). The precise placement of each rounding step within a formula is specified in §3 where that formula is defined; the placement matters, because rounding a running product differs from rounding a final sum.

### 2.6. Optimistic Concurrency on Bond Posting

Posting a restoration bond to a permit is guarded by optimistic concurrency control against the parent permit's `version`. A bond-post request must carry `expected_permit_version` as a required field, holding the `version` of the target permit that the client last observed. If `expected_permit_version` does not equal the permit's current `version`, the request is rejected with `ERR_STALE_PERMIT_VERSION` (HTTP 412). Because a permit's bond may be re-posted to supersede an earlier bond — for example to raise the amount before issuance — a successful post advances the permit's `version` by one; a subsequent post that still carries the older value is therefore refused as stale, ensuring the client cannot overwrite a bond state it has not observed. This is the only endpoint that accepts a version field; no other operation takes one.

### 2.7. Hierarchical Consistency and Revocation Cascades

The permit aggregate maintains immediate, whole-system consistency: when a parent transition renders downstream occupancy invalid, the server drives the dependent children through their own transitions in the same operation rather than leaving them stranded. The principal example is revocation. When a permit is driven to `REVOKED`, every lane closure still in `PLANNED`, `ACTIVE`, or `RESTORATION_PENDING` is voided, and every sidewalk obstruction still `ACTIVE` is voided. If a voided closure had never reached `RESTORED`, its parent restoration bond is driven from `POSTED` to `FORFEITED`. Each such cascaded mutation independently refreshes the touched resource's `updated_at` and increments its `version`, and any segment counters affected by a voided closure are adjusted as described in §3.

### 2.8. Nested Resource Retrieval and Path Validation

Many endpoints address a child through its parent — a lane closure, bond, plan, obstruction, or agreement reached under a permit, or a closure listed under a street segment. The system validates path identifiers strictly left to right and rejects at the first identifier that does not resolve. A request naming a permit that does not exist fails with `ERR_PERMIT_NOT_FOUND` (HTTP 404) before any child is considered; a request under a missing street segment fails with `ERR_SEGMENT_NOT_FOUND`, and a request under a missing sidewalk span fails with `ERR_SPAN_NOT_FOUND`. A lane closure, restoration bond, traffic-control plan, or encroachment agreement named in the path but absent fails with `ERR_CLOSURE_NOT_FOUND`. When a request body references an applicant that does not exist, it fails with `ERR_APPLICANT_NOT_FOUND`.

### 2.9. Validation Precedence

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role/ownership authorization (`ERR_UNAUTHORIZED`, and for the segregation-of-duties gate `ERR_SEGREGATION_OF_DUTIES`). Existence of every path- and body-referenced resource is checked next (the 404 family above). After existence come date-range sanity checks (`ERR_INVALID_DATE_RANGE`), then state-machine preconditions (`ERR_INVALID_PERMIT_STATE`, `ERR_PERMIT_NOT_ISSUED`, `ERR_INVALID_CLOSURE_STATE`, `ERR_INVALID_STATE`, `ERR_NOT_YET_EXPIRED`), then the bond-post optimistic-concurrency check (`ERR_STALE_PERMIT_VERSION`).

Business rules follow in this order: safety gates for issuance and plan approval (`ERR_TCP_NOT_APPROVED`, `ERR_FLAGGERS_REQUIRED`); referential and clearance conflicts for new occupancy (`ERR_CLOSURE_CONFLICT`, `ERR_SIDEWALK_BUFFER_CONFLICT`, `ERR_ADA_CLEARANCE`); the utility-cut moratorium (`ERR_UTILITY_CUT_MORATORIUM`); the outstanding-occupancy gate for close-out and bond release (`ERR_CLOSURES_OUTSTANDING`); and the fiscal sufficiency gate for the bond (`ERR_BOND_INSUFFICIENT`). Well-formedness of the request body — required fields present, correctly typed, and enum values in range — is checked last and surfaces as `ERR_INVALID_REQUEST` (HTTP 400). The effect of this ordering is that, for example, a caller who is not authorized never learns whether the resource exists, and a mid-flight state violation surfaces before a body-shape complaint.

### 2.10. The Logical Clock

All time-dependent behavior reads a server-controlled logical clock rather than wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and it holds that value until explicitly moved; before any clock call it never reflects real wall-clock time. An administrative capability sets the clock to a supplied `to_iso8601` instant. Occupancy durations, the `issued_at` stamp, the `actual_start_date` and `actual_end_date` on a permit, expiration eligibility, and moratorium comparisons all read this clock.

## 3. Business Logic & Workflows

### 3.1. Foundational Resources: Applicants, Segments, and Spans

Before any permit can exist, a `PlatformAdmin` registers the reference resources the permit will point at. An applicant is registered with its `company_name` (the legal name of the contractor organization), its municipal `license_number`, and a primary `contact_email`. Any registered applicant, as well as an administrator, may later read an applicant record back.

A street segment describes one roadway block face and is created with a human `block_label`, a `zone_class`, the `last_repaved_date` (in `YYYY-MM-DD` form), and a `roadway_lane_count`. The `zone_class` is one of `RESIDENTIAL`, `COMMERCIAL`, or `ARTERIAL`, and it drives both fee rates and the length of the utility-cut moratorium. An optional `moratorium_waived` flag defaults to false; when set true it administratively suspends the utility-cut moratorium for that segment.

At the moment a segment is created, the system computes its `moratorium_end_date`: take the `last_repaved_date` and add a whole number of calendar years determined by the zone — 2 years for a `RESIDENTIAL` segment, 3 years for a `COMMERCIAL` segment, and 5 years for an `ARTERIAL` segment. A segment also exposes a derived `active_lane_closure_count`, which begins at 0 and reflects the number of lane closures currently occupying the segment; its maintenance is described with lane-closure activation and restoration below.

A sidewalk span describes one run of sidewalk and is created with a `block_label`, a `side` of the block that is one of `NORTH`, `SOUTH`, `EAST`, or `WEST`, and a total `width_ft` in feet. It also carries `ada_min_clearance_ft`, the minimum pedestrian clearance in feet that any obstruction on the span must leave passable; this defaults to 4.0 feet when not supplied. Segments and spans are readable by administrators, applicants, and reviewers, and each exposes a listing of the occupancy records tied to it — a segment lists the lane closures whose `street_segment_id` points at it, and a span lists the obstructions whose `sidewalk_span_id` points at it.

### 3.2. Permit Drafting and the Review Loop

A permit is the organizing entity. An `Applicant` drafts one by supplying the `applicant_id` of the owning applicant (which must equal the caller's `X-User-ID`), the `street_segment_id` of the governed block, a `primary_obstruction_type` that is one of `LANE`, `FULL_ROAD`, or `SIDEWALK` and sets the scope used for the estimated occupancy fee, a `requested_start_date`, and a `requested_end_date`. An optional `requires_utility_cut` flag defaults to false and records whether the requested work involves a pavement cut. The `requested_end_date` must be strictly after the `requested_start_date`; otherwise the draft is rejected with `ERR_INVALID_DATE_RANGE`. A new permit begins in `DRAFT`. Permits may be fetched individually by any role, and listed — filtered by `applicant_id`, `street_segment_id`, or `status` query parameters — by administrators, reviewers, and applicants.

The permit lifecycle threads through the states `DRAFT`, `UNDER_REVIEW`, `RETURNED_FOR_REVISION`, `APPROVED`, `ISSUED`, and the terminal states `CLOSED_OUT`, `EXPIRED`, and `REVOKED`. The owning applicant submits a permit for review, moving it from `DRAFT` to `UNDER_REVIEW`; the same submit action also carries a permit from `RETURNED_FOR_REVISION` back to `UNDER_REVIEW`, forming the revision loop. Submitting a permit that is in neither `DRAFT` nor `RETURNED_FOR_REVISION` is rejected with `ERR_INVALID_PERMIT_STATE`, and a submit by anyone other than the owning applicant is an authorization failure.

A `PermitReviewer` renders a decision on a permit that is `UNDER_REVIEW`, supplying an `outcome` and optional `review_notes`. When the `outcome` approves the permit, it transitions to `APPROVED` and the reviewer's `X-User-ID` is captured as `assigned_reviewer_user_id`. When the `outcome` returns the permit for rework, it transitions to `RETURNED_FOR_REVISION` and the supplied `review_notes` are stored. A decision on a permit that is not `UNDER_REVIEW` is rejected with `ERR_INVALID_PERMIT_STATE`.

### 3.3. Traffic-Control Plans and Restoration Bonds

Two prerequisites must be satisfied before a permit can be issued: an approved traffic-control plan and a sufficient restoration bond.

The owning applicant attaches a traffic-control plan to a permit, supplying a `device_list` (the array of traffic-control devices to be deployed, such as cones, barricades, and signs), a `requires_flaggers` boolean, an optional `flagger_count` that defaults to 0, and a `setback_ft` buffer distance in feet from the work zone to live traffic. A newly attached plan starts in `SUBMITTED`. A permit's plans may be listed by the applicant, reviewers, and administrators. A `PermitReviewer` then decides the plan, supplying an `outcome` and optional `review_notes`. Approval moves the plan from `SUBMITTED` to `APPROVED` and stores the `review_notes`; rejection moves it from `SUBMITTED` to `REJECTED` and likewise stores the `review_notes`. There is one safety gate on approval: if the plan's `requires_flaggers` is true, its `flagger_count` must be at least 1, or the approval is rejected with `ERR_FLAGGERS_REQUIRED`. Deciding a plan that is not `SUBMITTED` is rejected with `ERR_INVALID_STATE`.

The owning applicant posts a restoration bond to a permit, supplying `posted_cents` (the bond amount) and `expected_permit_version` (see the optimistic-concurrency rule in §2.6). The system computes the minimum `required_cents` as the larger of a fixed floor of 50000 cents and twice the permit's estimated occupancy fee — that is, the estimated occupancy fee (the estimated variant defined in §3.4, using the permit's requested window) multiplied by 2, compared against 50000 cents, taking whichever is greater. If `posted_cents` is less than `required_cents`, the post is rejected with `ERR_BOND_INSUFFICIENT`. On a successful post the bond is created in `POSTED` with `held_cents` set equal to `posted_cents`, `provisional_refund_cents` initialized to `posted_cents`, `refunded_cents` and `forfeited_cents` at 0, and the parent permit's `version` advanced by one. A permit's bond may be re-posted to supersede a prior one; a permit exposes its bond (zero or one) as a listing. Across a bond's life the invariant `held_cents` plus `refunded_cents` plus `forfeited_cents` always equals the original `posted_cents`.

### 3.4. Issuing the Permit and the Occupancy Fee

A `PermitReviewer` issues a permit that is `APPROVED`, carrying it to `ISSUED`. Issuance is gated by three preconditions, checked in the precedence of §2.9. The permit's traffic-control plan must exist and be `APPROVED`, or issuance is rejected with `ERR_TCP_NOT_APPROVED`. A restoration bond in status `POSTED` must exist with `posted_cents` at least the required amount, or issuance is rejected with `ERR_BOND_INSUFFICIENT`. And the segregation-of-duties rule applies: the issuing `X-User-ID` must differ from the permit's `assigned_reviewer_user_id`, so the reviewer who approved a permit may not issue it; a match is rejected with `ERR_SEGREGATION_OF_DUTIES`. Issuing a permit that is not `APPROVED` is rejected with `ERR_INVALID_PERMIT_STATE`.

On issuance the system computes and stores several derived amounts, then sets `valid_until` equal to the `requested_end_date` and stamps `issued_at` with the current logical-clock time.

The **occupancy fee** is a tiered, capped charge. Its inputs are the permit's governing street segment's `zone_class` and the permit's `primary_obstruction_type`. Three per-zone constants apply: a base component of 5000 cents for `RESIDENTIAL`, 10000 cents for `COMMERCIAL`, and 20000 cents for `ARTERIAL`; a daily rate of 500 cents for `RESIDENTIAL`, 1500 cents for `COMMERCIAL`, and 3000 cents for `ARTERIAL`; and a fee cap of 200000 cents for `RESIDENTIAL`, 500000 cents for `COMMERCIAL`, and 1000000 cents for `ARTERIAL`. An area factor scales the obstruction scope: 1.0 for `SIDEWALK`, 2.0 for `LANE`, and 3.5 for `FULL_ROAD`. The duration in whole days is the number of days from the window's start date to its end date. The fee is computed by multiplying the daily rate by the area factor and by the duration in days, rounding that product half-up to a whole cent, adding the zone's base component, and then taking the smaller of that sum and the zone's cap. In the **estimated variant** computed at issuance, the duration uses the permit's `requested_start_date` through `requested_end_date` window and the result is stored as `estimated_fee_cents`.

The **total permit charge** is computed at issuance from three components: the estimated occupancy fee just computed, a fixed traffic-control-plan review fee of 7500 cents, and a fixed inspection fee of 4000 cents. The municipal surcharge is 7.25 percent applied per component: for each of the three components, multiply the component by 0.0725, round that product half-up to a whole cent, and then sum the three rounded results — the surcharge is deliberately rounded per line item and never on the aggregate. The result is stored as `surcharge_cents`. The `total_charge_cents` is the sum of the three components plus `surcharge_cents`.

### 3.5. Lane Closures, Conflicts, and the Utility-Cut Moratorium

Once a permit is `ISSUED`, the owning applicant may plan lane closures under it. Creating a lane closure requires the parent permit to be `ISSUED`; otherwise the attempt is rejected with `ERR_PERMIT_NOT_ISSUED`. A closure is created with the `street_segment_id` of the roadway resource it occupies, an `obstruction_type` that is one of `LANE` or `FULL_ROAD`, a `start_date`, an `end_date`, and an optional `requires_utility_cut` flag that defaults to false. The occupancy interval is half-open — it includes the `start_date` and excludes the `end_date` — and the `end_date` must be strictly after the `start_date`, or the request is rejected with `ERR_INVALID_DATE_RANGE`. A newly created closure begins in `PLANNED`.

Two occupancy rules guard creation. First, a new closure must not overlap any existing closure in `PLANNED` or `ACTIVE` status on the same street segment. Because the intervals are half-open, two closures that merely touch — where one's `end_date` equals the other's `start_date` — do not overlap and are permitted; any true overlap is rejected with `ERR_CLOSURE_CONFLICT`. Second, when the new closure's `requires_utility_cut` is true, it is subject to the pavement-cut moratorium: its `start_date` must fall on or after the segment's `moratorium_end_date`. A `start_date` strictly before the `moratorium_end_date` is rejected with `ERR_UTILITY_CUT_MORATORIUM`, and a `start_date` exactly equal to the `moratorium_end_date` is allowed. This moratorium check is skipped entirely when the segment's `moratorium_waived` flag is true.

The owning applicant activates a `PLANNED` closure, moving it to `ACTIVE`; activation requires the parent permit to be `ISSUED`. Activation increments the occupied segment's `active_lane_closure_count` by one, and if the permit's `actual_start_date` is still unset, it is set to the current logical-clock date at this first activation. Activating a closure that is not `PLANNED` is rejected with `ERR_INVALID_CLOSURE_STATE`. A permit's closures may be listed by the applicant, reviewers, inspectors, and administrators.

### 3.6. Sidewalk Obstructions and ADA Clearance

Sidewalk occupancy runs on a parallel track. With the parent permit `ISSUED` (otherwise `ERR_PERMIT_NOT_ISSUED`), the owning applicant creates a sidewalk obstruction naming the `sidewalk_span_id` it occupies, a `start_date`, an `end_date`, and the `maintained_clearance_ft` the applicant will keep passable. As with closures, the interval is half-open and the `end_date` must be strictly after the `start_date`, else `ERR_INVALID_DATE_RANGE`. A sidewalk obstruction is created directly in `ACTIVE`.

Two rules guard creation. The maintained clearance must meet the span's floor: `maintained_clearance_ft` must be at least the span's `ada_min_clearance_ft`, or the request is rejected with `ERR_ADA_CLEARANCE`. And a temporal buffer applies against congestion: a new obstruction must keep a gap of at least 3 days from every `ACTIVE` obstruction already on the same sidewalk span. Unlike the lane-closure rule, adjacency is not allowed here — the separation must be a full 3 days or more, so obstructions that merely touch or fall within the 3-day buffer are rejected with `ERR_SIDEWALK_BUFFER_CONFLICT`. The owning applicant, or an inspector, later marks an `ACTIVE` obstruction restored, moving it to `RESTORED`; attempting this on an obstruction that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`. A permit's obstructions may be listed by the applicant, reviewers, inspectors, and administrators.

### 3.7. Restoration, Inspection Sign-Off, and Bond Release

When the physical work is complete, the owning applicant requests a restoration inspection on a lane closure, moving it from `ACTIVE` to `RESTORATION_PENDING`. This same request also carries a closure from `RESTORATION_REJECTED` back to `RESTORATION_PENDING`, forming the restoration loop for closures that failed a prior inspection. Requesting restoration from any other state is rejected with `ERR_INVALID_CLOSURE_STATE`. The request accepts an optional `estimated_deficiency_cents`, the applicant's own estimate of any restoration shortfall, which is stored on the closure and triggers a fresh preview of the bond refund.

An `Inspector` signs off a closure that is `RESTORATION_PENDING`, supplying a `result` and an `assessed_deficiency_cents`. When the `result` passes, the closure moves to `RESTORED`, and the occupied segment's `active_lane_closure_count` is decremented by one. When the `result` fails, the closure moves to `RESTORATION_REJECTED`. In both outcomes the supplied `assessed_deficiency_cents` is recorded and the signing inspector's `X-User-ID` is captured as `inspector_user_id`. Signing off a closure that is not `RESTORATION_PENDING` is rejected with `ERR_INVALID_CLOSURE_STATE`. The segment's `active_lane_closure_count` is thus maintained as a non-negative running total: raised by one at each activation and lowered by one whenever a counted closure is restored or voided, and it never drops below zero.

The **bond refund** is a waterfall over the posted amount: from `posted_cents`, subtract the total restoration deficiency across the relevant closures, then subtract the permit's `cumulative_penalty_cents`; the refund is that difference or zero, whichever is greater (it is floored at zero). Whatever is not refunded is forfeited — the forfeited amount is `posted_cents` minus the refund. This waterfall is evaluated in two variants that differ only in which closures they sum and which deficiency figure they use. The **provisional variant** is recomputed each time a closure enters `RESTORATION_PENDING` via a restoration request: it sums the `estimated_deficiency_cents` of the permit's closures currently in `RESTORATION_PENDING`, and its result is stored as the bond's `provisional_refund_cents` as a preview. The **final variant** is computed at bond release: it sums the `assessed_deficiency_cents` of the permit's closures in `RESTORED`, and its result is stored as the bond's `refunded_cents`, with `forfeited_cents` set to `posted_cents` minus that refund.

A `PermitReviewer` or a `PlatformAdmin` releases a bond that is `POSTED`, moving it to `RELEASED`. Release is gated: every lane closure on the bond's permit must be terminal — in `RESTORED` or `VOIDED` — or the release is rejected with `ERR_CLOSURES_OUTSTANDING`. On release the final refund is computed as above, `forfeited_cents` is set to `posted_cents` minus `refunded_cents`, and `held_cents` is set to 0. Releasing a bond that is not `POSTED` is rejected with `ERR_INVALID_STATE`.

### 3.8. Encroachment Agreements, Violations, and Penalties

Some occupancies extend into long-term encroachment on the right-of-way. The owning applicant proposes an encroachment agreement on a permit, supplying a requested `term_months` and a `proposed_fee_cents` (the applicant-proposed annual fee). The agreement is created in `PROPOSED`. A `PermitReviewer` executes a proposed agreement, but only while the parent permit is `ISSUED`; execution against a non-`ISSUED` permit is rejected with `ERR_PERMIT_NOT_ISSUED`. Execution moves the agreement from `PROPOSED` to `EXECUTED` and locks `agreed_fee_cents` equal to the `proposed_fee_cents` at that moment. Executing an agreement that is not `PROPOSED` is rejected with `ERR_INVALID_STATE`. A permit's agreements may be listed by the applicant, reviewers, and administrators.

Enforcement is handled by the `EnforcementOfficer`, who issues a violation notice against a permit, supplying a `violation_type` — one of `UNPERMITTED_WORK`, `TCP_VIOLATION`, `OVERSTAY`, or `RESTORATION_FAILURE` — and an optional free-text `note`. The `penalty_cents` for the notice escalates with the permittee's history on that permit. Let the prior count be the number of violation notices already recorded on the permit, ordered by `created_at` ascending. The penalty is a base of 15000 cents scaled by one plus 0.5 times that prior count; that scaled product is rounded half-up to a whole cent and then capped at a maximum of 100000 cents — the penalty is the smaller of the rounded escalated product and 100000 cents. The computed penalty is added to the permit's `cumulative_penalty_cents`. Because the notice itself is an immutable record, it carries only its own `id` and `created_at`, its `permit_id`, its `violation_type`, its `penalty_cents`, and its `note`.

Issuing a violation notice can trip the revocation threshold. If, after the new penalty is added, the permit's `cumulative_penalty_cents` is at least 37500 cents and the permit is currently `ISSUED`, the system automatically revokes the permit as described next.

### 3.9. Close-Out, Expiration, and Revocation

There are three ways an issued permit reaches a terminal state.

**Close-out** is the ordinary settlement path. A `PermitReviewer` or an `Inspector` closes out a permit that is `ISSUED`, moving it to `CLOSED_OUT`. Close-out requires that every lane closure and every sidewalk obstruction on the permit be terminal — each in `RESTORED` or `VOIDED`; any non-terminal occupancy rejects the close-out with `ERR_CLOSURES_OUTSTANDING`. On close-out the permit's `actual_end_date` is set to the current logical-clock date, and the **final variant** of the occupancy fee is computed and stored as `final_fee_cents`. The final variant uses the same tiered formula as the estimated variant but measures the true occupancy window: its duration in whole days runs from the permit's `actual_start_date` (the date of the first lane-closure activation) to its `actual_end_date`. Because the true window can exceed the requested one, an overstay yields a strictly larger fee than the estimate. If no closure was ever activated and `actual_start_date` is therefore unset, the final fee equals the previously computed `estimated_fee_cents`. Closing out a permit that is not `ISSUED` is rejected with `ERR_INVALID_PERMIT_STATE`.

**Expiration** retires a permit whose validity has lapsed. A `PlatformAdmin` expires a permit that is `ISSUED`, moving it to `EXPIRED`, but only once the logical-clock date is strictly after the permit's `valid_until`. An expiration attempted while the clock date is on or before `valid_until` is rejected with `ERR_NOT_YET_EXPIRED`; attempting to expire a permit that is not `ISSUED` is rejected with `ERR_INVALID_PERMIT_STATE`.

**Revocation** is the enforcement path, triggered by the system rather than by a direct request. When a violation notice pushes `cumulative_penalty_cents` to at least 37500 cents while the permit is `ISSUED`, the permit transitions to `REVOKED` and a consistency cascade fires across its children. Every lane closure still in `PLANNED`, `ACTIVE`, or `RESTORATION_PENDING` is voided to `VOIDED`; each closure that had been counted against its segment — that is, one voided out of `ACTIVE` or `RESTORATION_PENDING` — decrements that segment's `active_lane_closure_count` by one, while a closure voided out of `PLANNED` had never been counted and leaves the count unchanged. Every sidewalk obstruction still `ACTIVE` is voided to `VOIDED`. Finally, if any closure is voided without ever having reached `RESTORED`, the permit's restoration bond is driven from `POSTED` to `FORFEITED`: its `forfeited_cents` is set to the amount currently `held_cents`, and both `held_cents` and `refunded_cents` are set to 0.

## 4. Endpoint Definitions

Operations that create a new resource — a stand-alone record such as an applicant, or a new child added to a permit such as a lane closure, bond, or violation notice — return `201 Created`. Operations that modify an existing resource, including lifecycle transitions and sign-offs, return `200 OK`, as do all read (`GET`) operations and the logical-clock control endpoint. Every request must carry the `X-User-ID` and `X-User-Role` headers described in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/applicants` | Register a contractor/permittee | PlatformAdmin |
| GET | `/applicants/{id}` | Fetch an applicant | PlatformAdmin, Applicant |
| POST | `/street-segments` | Create a roadway segment; computes its moratorium end date | PlatformAdmin |
| GET | `/street-segments/{id}` | Fetch a street segment | PlatformAdmin, Applicant, PermitReviewer |
| GET | `/street-segments/{id}/lane-closures` | List lane closures occupying this segment | PlatformAdmin, Applicant, PermitReviewer |
| POST | `/sidewalk-spans` | Create a sidewalk span resource | PlatformAdmin |
| GET | `/sidewalk-spans/{id}` | Fetch a sidewalk span | PlatformAdmin, Applicant, PermitReviewer |
| GET | `/sidewalk-spans/{id}/obstructions` | List obstructions on this span | PlatformAdmin, Applicant, PermitReviewer |
| POST | `/permits` | Create a draft permit | Applicant |
| GET | `/permits/{id}` | Fetch a permit | Applicant, PermitReviewer, Inspector, EnforcementOfficer, PlatformAdmin |
| GET | `/permits` | List and filter permits | PlatformAdmin, PermitReviewer, Applicant |
| POST | `/permits/{id}/submit` | Submit a draft or returned permit for review | Applicant |
| POST | `/permits/{id}/decision` | Approve or return a permit under review | PermitReviewer |
| POST | `/permits/{id}/issue` | Issue an approved permit; computes fees and surcharge | PermitReviewer |
| POST | `/permits/{id}/close-out` | Close out an issued permit; computes final fee | PermitReviewer, Inspector |
| POST | `/permits/{id}/expire` | Expire an issued permit past its validity | PlatformAdmin |
| POST | `/permits/{id}/traffic-control-plan` | Attach and submit a traffic-control plan | Applicant |
| GET | `/permits/{id}/traffic-control-plans` | List a permit's traffic-control plans | Applicant, PermitReviewer, PlatformAdmin |
| POST | `/traffic-control-plans/{id}/decision` | Approve or reject a submitted plan | PermitReviewer |
| POST | `/permits/{id}/bond` | Post or supersede a restoration bond | Applicant |
| GET | `/permits/{id}/bond` | List a permit's restoration bond | Applicant, PermitReviewer, PlatformAdmin |
| POST | `/bonds/{id}/release` | Release a bond; computes final refund | PermitReviewer, PlatformAdmin |
| POST | `/permits/{id}/lane-closures` | Create a planned lane closure | Applicant |
| GET | `/permits/{id}/lane-closures` | List a permit's lane closures | Applicant, PermitReviewer, Inspector, PlatformAdmin |
| POST | `/lane-closures/{id}/activate` | Activate a planned closure | Applicant |
| POST | `/lane-closures/{id}/request-restoration` | Report work complete and request inspection | Applicant |
| POST | `/lane-closures/{id}/sign-off` | Sign off restoration (pass or fail) | Inspector |
| POST | `/permits/{id}/sidewalk-obstructions` | Create an active sidewalk obstruction | Applicant |
| GET | `/permits/{id}/sidewalk-obstructions` | List a permit's sidewalk obstructions | Applicant, PermitReviewer, Inspector, PlatformAdmin |
| POST | `/sidewalk-obstructions/{id}/complete-restoration` | Mark a sidewalk obstruction restored | Applicant, Inspector |
| POST | `/permits/{id}/encroachment-agreement` | Propose a long-term encroachment agreement | Applicant |
| GET | `/permits/{id}/encroachment-agreements` | List a permit's encroachment agreements | Applicant, PermitReviewer, PlatformAdmin |
| POST | `/encroachment-agreements/{id}/execute` | Execute a proposed agreement | PermitReviewer |
| POST | `/permits/{id}/violations` | Issue a violation notice; may auto-revoke the permit | EnforcementOfficer |
| GET | `/permits/{id}/violations` | List a permit's violation notices | PermitReviewer, EnforcementOfficer, PlatformAdmin, Applicant |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_APPLICANT_NOT_FOUND` | 404 |
| `ERR_SEGMENT_NOT_FOUND` | 404 |
| `ERR_SPAN_NOT_FOUND` | 404 |
| `ERR_CLOSURE_NOT_FOUND` | 404 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_INVALID_PERMIT_STATE` | 409 |
| `ERR_PERMIT_NOT_ISSUED` | 409 |
| `ERR_INVALID_CLOSURE_STATE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NOT_YET_EXPIRED` | 409 |
| `ERR_STALE_PERMIT_VERSION` | 412 |
| `ERR_TCP_NOT_APPROVED` | 409 |
| `ERR_FLAGGERS_REQUIRED` | 422 |
| `ERR_CLOSURE_CONFLICT` | 409 |
| `ERR_SIDEWALK_BUFFER_CONFLICT` | 409 |
| `ERR_ADA_CLEARANCE` | 422 |
| `ERR_UTILITY_CUT_MORATORIUM` | 409 |
| `ERR_CLOSURES_OUTSTANDING` | 409 |
| `ERR_BOND_INSUFFICIENT` | 422 |
| `ERR_INVALID_REQUEST` | 400 |
