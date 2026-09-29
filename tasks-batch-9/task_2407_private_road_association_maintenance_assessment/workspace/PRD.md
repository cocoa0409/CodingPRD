# Private Road Association Maintenance & Assessment API — Product Requirements Document

## 1. Introduction

Rural private road associations occupy an awkward legal and financial position. They carry the obligations of a public works department — grading, culvert replacement, snow and dust control, bridge load ratings, emergency-vehicle access standards — but they raise their money the way a homeowners association does, by spreading a budget across a handful of deeded parcels whose owners are also the voters. The paperwork that holds this together is scattered across recorded deeds, road-maintenance covenants, easement grants, contractor bid files, and a reserve ledger that nobody reconciles until a culvert collapses. When a parcel is subdivided, when an owner stops paying, or when a paving contractor withdraws a bid after award, the association's officers discover that the record no longer agrees with itself.

This service is the association's system of record. It holds the membership roll tied to parcel deeds, computes the annual assessment under either of two competing allocation methods, runs the balloting for special assessments with per-project-type vote thresholds, tracks delinquency remedies up to and including lien filing and gated access restriction, solicits and awards contractor bids under a lowest-responsive-bid rule, and maintains a reserve fund whose funding posture feeds back into what the board is allowed to approve. Every one of those processes touches the others: a lien filing voids the delinquent owner's outstanding ballots, a project award drains the reserve and thereby raises the vote threshold on every draft proposal, and a failed emergency-access inspection cancels paving projects and returns their reserve draws.

Two design commitments run through the whole specification. First, money and votes are computed with pinned evaluation orders and integer arithmetic, because an association that cannot reproduce last year's assessment roll to the cent cannot defend it. Second, offices are separated: the clerk who certifies a roll may not levy it, the treasurer who initiates a lien may not perfect it, and the commissioner who opens a solicitation may not award it. The API enforces both mechanically rather than by policy memo.

## 2. Global Specifications & System-Wide Principles

### 2.1. Identity, Roles, and the Separation of Association Offices

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the office that user is acting in. If either header is absent or blank, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The same error is returned when `X-User-Role` does not name one of the six recognised roles: `AssociationSecretary`, `AssessmentClerk`, `BoardTreasurer`, `RoadCommissioner`, `MemberOwner`, and `Contractor`. When the role is recognised but is not among those authorised for the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The six offices divide the work as follows. The `AssociationSecretary` keeps the membership roll, the parcel record, and the easement and connection file. The `AssessmentClerk` opens, certifies, and recalls assessment rolls and may post payments, but may never levy. The `BoardTreasurer` levies rolls, runs special-assessment balloting, and pursues delinquency remedies, but may never certify a roll. The `RoadCommissioner` owns the physical road — segments, emergency-access inspections, and maintenance projects. A `MemberOwner` is a deeded owner acting on their own membership. A `Contractor` is a bidding firm that sees the solicitation and manages only its own bids.

Five of the six roles carry an opaque identity. When `X-User-Role` is `AssociationSecretary`, `AssessmentClerk`, `BoardTreasurer`, `RoadCommissioner`, or `Contractor`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared against any record's `id`. The server does record it where a scaffold transition writes it: an `AssociationSecretary`'s identifier lands in `decided_by_user_id` on a connection request; a `BoardTreasurer`'s lands in `initiated_by_user_id` and later in `effectuated_by_user_id` on a delinquency action; a `RoadCommissioner`'s lands in `created_by_user_id` and later in `awarded_by_user_id` on a maintenance project; a `Contractor`'s lands in `contractor_user_id` on a bid. The `AssessmentClerk` identifier is recorded on no entity.

When `X-User-Role` is `MemberOwner`, by contrast, `X-User-ID` is the `id` of the acting `Member` row. Ownership checks on any resource that references a `Member` compare the resource's foreign-key field to `X-User-ID`: a ballot is the acting member's when its `member_id` equals `X-User-ID`; an assessment charge is the acting member's when its `member_id` equals `X-User-ID`; and a connection request may be filed by a `MemberOwner` only when the `Member` on the subdividing parent parcel is `X-User-ID`. A `Contractor` may withdraw only a bid whose `contractor_user_id` equals `X-User-ID`. Any of these mismatches yields `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

Segregation of duties operates on two levels. At the role level, certification and levy are held by different offices, so a single user cannot both certify and levy simply because no one role is authorised for both. At the user level, two operations additionally compare identifiers within the same role: awarding a maintenance project requires that `X-User-ID` differ from the project's `created_by_user_id`, and effectuating a delinquency remedy requires that `X-User-ID` differ from that remedy's `initiated_by_user_id`. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

### 2.3. Pagination and List Ordering

List endpoints accept two query parameters. `limit` caps the number of rows returned; it defaults to 10, may not be smaller than 1, and may not be larger than 100. `offset` is the number of rows to skip and defaults to 0; it may not be negative. A `limit` outside the permitted range or a negative `offset` is a request-shape failure and is rejected with `ERR_INVALID_REQUEST`.

Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending. The single exception is the assessment-roll listing, which is ordered by `fiscal_year` ascending and then by `created_at` ascending within a fiscal year.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` indicates whether rows remain beyond the current page.

### 2.4. Record Identity, Audit Fields, and the Logical Clock

All twelve persisted record types — associations, road segments, parcels, members, assessment rolls, assessment charges, special assessment proposals, ballots, maintenance projects, contractor bids, delinquency actions, and connection requests — carry the same four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, stamped when the row is first written.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every mutation of the row, including mutations that only touch derived fields.
- `version` (integer): an integer that starts at 1 and increments by one on every mutation of the row.

There are no record types in this system that omit `updated_at` or `version`; every one of the twelve carries the full set. This matters because derived fields are mutations in their own right: when a project award drains the reserve, the `Association` row's `reserve_balance_cents`, `reserve_funding_ratio`, and `reserve_posture` change, and that association's `updated_at` and `version` move accordingly. The same holds for a proposal whose tally totals shift because a ballot was voided, and for a member whose `standing_status` was recomputed by a cascade the member never requested.

Time is logical, not wall-clock. Before any client sets it, the server's logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. Every temporal rule in this specification — assessment due dates, the delinquency grace period, balloting windows, restriction intervals, work windows, and the paving cure buffer — is evaluated against this logical clock. An administrative test-driving capability moves the clock to a supplied instant, taking a single `to_iso8601` field and answering with an object carrying `current_utc`; it mutates no entity, but every subsequent request evaluates its temporal rules against the new instant. This capability is available to the `AssociationSecretary`, `AssessmentClerk`, `BoardTreasurer`, and `RoadCommissioner`.

### 2.5. Monetary Precision, Share Units, and Rounding Order

All money in this system is expressed in whole cents as integers, and every monetary rounding is round-half-up. There is no floating-point money and no fractional cent is ever stored. Where a computation must round, the point at which it rounds is part of the specification and is never left to the implementer's convenience.

Share units are the one exception to integer arithmetic. A parcel's `frontage_share_units` and `trip_share_units` are exact rational quantities and are not rounded at the point of computation; they are stored to four decimal places for display. Assessment allocations consume the exact values, not the displayed ones.

Three rounding orders are pinned and differ from one another:

- **Assessment allocation** rounds each parcel's final share to whole cents after the redistribution pass has completed, and then sums the rounded per-parcel amounts. It never rounds an intermediate subtotal, and it never rounds the total and then splits it.
- **The connection fee** rounds each of its four components to whole cents individually, and only then adds the four rounded integers. Summing the exact components and rounding once at the end produces a different and incorrect answer.
- **The lien payoff** rounds exactly once, at the end of whichever interest branch the association's policy selects.

Voting weights are integers, and the conversion from an assessed amount to a weight floors rather than rounds. Vote thresholds and the quorum are expressed in integer basis points, and every threshold comparison is performed as a cross-multiplication of integers so that no floating-point rounding can shift an outcome. `reserve_funding_ratio` is the one derived number that is not an integer: it is the reserve balance divided by the reserve target, rounded to four decimal places, and it exists for display only — no rule in this system compares against it.

### 2.6. Reserve Fund Accounting and Funding Posture

The association maintains a reserve fund against bridge and culvert replacement. Its `reserve_target_cents` is set at registration and must be at least 1. Its `reserve_balance_cents` is not a free-standing counter but a reconciled aggregate, recomputed from first principles on every event that moves reserve money: an assessment roll levy, a connection approval, a project award, a project cancellation, and the withdrawal of an awarded bid. The reconciliation takes the sum of `reserve_contribution_cents` over every assessment roll of the association whose `status` is `LEVIED`, adds the sum of `reserve_buyin_cents` over every connection request whose `status` is `APPROVED` and whose parcel sits on a road segment of this association, and subtracts the sum of `reserve_draw_cents` over every maintenance project on a segment of this association whose `status` is `AWARDED` or `COMPLETE`. Projects still in `BID_SOLICITATION` and projects that were `CANCELLED` contribute nothing to the subtraction.

From that balance the system derives two further fields. `reserve_funding_ratio` is the balance divided by the target, rounded to four decimals for display. `reserve_posture` is one of `UNDERFUNDED`, `ADEQUATE`, or `FULLY_FUNDED`, and it is resolved by integer cross-multiplication rather than by comparing the ratio: the posture is `FULLY_FUNDED` when the balance is at least the target; otherwise it is `ADEQUATE` when the balance multiplied by one hundred is at least the target multiplied by sixty — so a balance of exactly sixty percent of target is `ADEQUATE` — and otherwise it is `UNDERFUNDED`. A newly registered association starts with a `reserve_balance_cents` of 0, a `reserve_funding_ratio` of 0, and a `reserve_posture` of `UNDERFUNDED`.

Posture is not merely reported; it is an input to governance. Whenever `reserve_balance_cents` changes, the funding ratio and the posture are recomputed, and because the posture may have moved, every special assessment proposal of that association whose `status` is `DRAFT` has its `required_threshold_bps` recomputed as part of the same operation. Proposals that have already opened balloting keep the threshold frozen for their round.

### 2.7. The Emergency-Vehicle Access Standard

Each road segment carries an `emergency_access_grade` of `UNKNOWN`, `COMPLIANT`, or `DEFICIENT`. A newly recorded segment is `UNKNOWN` — the standard cannot be asserted until an inspection has actually measured the road — and it stays `UNKNOWN` until the first access inspection regrades it. A segment also carries `required_turnouts`, a derived integer count of the emergency passing turnouts the standard demands: take the segment's `length_feet`, divide by the eight-hundred-foot turnout spacing, round the quotient up to the next whole number, subtract one, and treat any negative result as zero.

A segment grades as `COMPLIANT` only when all five conditions hold at once: its `width_feet` is at least twenty feet; its `max_grade_pct` is no more than twelve percent; `turnaround_present` is true; its `turnout_count` is at least `required_turnouts`; and either `bridge_present` is false, or `bridge_present` is true and `bridge_load_rating_tons` is both non-null and at least forty tons. If any of those fails, the grade is `DEFICIENT`. The bridge clause disappears entirely on a segment with no bridge, and both boundary comparisons are inclusive — a road exactly twenty feet wide on exactly a twelve percent grade passes.

The grade gates three operations, and it gates them at different strictnesses. Awarding a `PAVING` project requires the segment to be `COMPLIANT`. Effectuating an `ACCESS_RESTRICTION` requires the segment to be `COMPLIANT`, because the association may not lock a gate on a road that already fails the standard for fire apparatus. Approving a new-lot connection requires only that the segment not be `DEFICIENT`, so an as-yet-uninspected `UNKNOWN` segment does not block a connection. All three rejections carry `ERR_EMERGENCY_ACCESS_DEFICIENT` (HTTP 409). The segment's `culvert_count` and `surface_type` — one of `GRAVEL`, `CHIP_SEAL`, or `PAVED` — are recorded for reserve planning and work scoping but do not enter the compliance test.

### 2.8. Cascading Reconciliation and Derived-Field Consistency

Many of this system's fields are projections rather than stored decisions, and the server maintains them without being asked. Two member-level projections are worth naming here because they are re-run by a wide set of unrelated operations.

Member fiscal standing is a projection over the member's charges. If `standing_status` is `PENDING_DEED_VERIFICATION` it is left alone, because deed verification is the only exit from that state. Otherwise, if any charge of that member has `status` `LIEN_ENCUMBERED`, the standing becomes `LIEN_FILED`; failing that, if any charge of that member has `status` `DELINQUENT`, the standing becomes `DELINQUENT`; failing both, the standing becomes `GOOD_STANDING`. In the same reconciliation, `encumbered_principal_cents` is set to the sum of `lien_amount_cents` over every delinquency action of that member whose `status` is `EFFECTIVE`. This projection runs on every mutation that changes an assessment charge's `status` or a delinquency action's `status`.

Member access standing is a separate projection over the member's delinquency actions, and neither dimension constrains the other. If any delinquency action of that member is `EFFECTIVE` with `action_type` `ACCESS_RESTRICTION`, `access_status` becomes `RESTRICTED`; failing that, if any is `EFFECTIVE` with `action_type` `NOTICE`, `access_status` becomes `WARNED`; failing both, `access_status` becomes `UNRESTRICTED`. `VOIDED` actions contribute to neither field. The companion counter `restricted_days_used` is the sum of `restriction_days` over that member's `ACCESS_RESTRICTION` actions whose `status` is `EFFECTIVE` or `RELEASED`, and the forty-five-day ceiling it is checked against is a per-fiscal-year ceiling, the fiscal year being that of the underlying charge's roll. The counter is monotone. Releasing a restriction does not give the days back; consumed restriction days stay consumed for the fiscal year.

Because a member row carries both dimensions independently, combinations that look contradictory are legitimate: a member may be `LIEN_FILED` and `UNRESTRICTED` at once when a lien was filed but no gate was closed, and `GOOD_STANDING` and `WARNED` at once when a notice was served and the charge was subsequently paid.

The general shape of a cascade in this system is that a single client request may mutate three or four rows. Each such secondary mutation refreshes that row's `updated_at` and increments its `version`, exactly as a direct write would. Cascades are applied immediately within the request, not deferred.

### 2.9. Optimistic Concurrency on Parent Records

Three write operations take an explicit expected-version field naming their parent record's `version`. These fields are required inputs, not optional hints, and a request that omits one fails request-shape validation.

Submitting a contractor bid against a maintenance project must carry `expected_project_version` holding the `version` of the target `MaintenanceProject` as the client last observed it. If that value does not equal the project's current `version`, the submission is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). The check earns its place because the product deliberately lets a firm's newer bid supersede its own earlier bid: a submission written against a stale project cannot be distinguished from a legitimate revision by state alone, so the version comparison is the only thing that separates them.

Casting a ballot must carry `expected_proposal_version` holding the `version` of the target `SpecialAssessmentProposal` as the client last observed it, and revoking a ballot must carry the same field for the ballot's proposal. A mismatch with the proposal's current `version` is rejected with `ERR_STALE_PROPOSAL_VERSION` (HTTP 412). Recasting is legal here too — the prior ballot is superseded — so a second cast from the same member is not a state violation; the version comparison is what rejects a cast written against a tally the client never saw, including a tally changed by a lien-driven ballot void.

Reclassifying a parcel must carry `expected_parcel_version` holding the `version` of the target `Parcel` as the client last observed it. A mismatch is rejected with `ERR_STALE_PARCEL_VERSION` (HTTP 412). Frontage and usage-class edits are individually legal whenever the parcel is `ACTIVE` and no roll is `CERTIFIED`, so a second edit is not a state violation; the version comparison is what stops a stale edit from silently overwriting a reclassification the client never observed.

No other endpoint in this system accepts a version field, and no other endpoint performs a version check.

### 2.10. Request Validation Precedence and Path Resolution

Path identifiers are resolved strictly left to right. A request naming a parcel and then a connection request under it fails with the parcel's not-found error before the connection request is even looked for, and the response carries the not-found error of the *first* identifier in the path that does not resolve.

More generally, every request walks the following checks in this exact order, and the first failure is the error returned. Where several checks could all fire, the earlier one masks the later ones.

1. `X-User-ID` and `X-User-Role` are both present and non-blank — otherwise `ERR_UNAUTHENTICATED` (401).
2. `X-User-Role` names one of the six declared roles — otherwise `ERR_UNAUTHENTICATED` (401).
3. The role is among the endpoint's authorised roles — otherwise `ERR_FORBIDDEN_ROLE` (403).
4. Request body and query shape: required fields are present, enum members are recognised, numeric fields are non-negative, integer fields are integral, dates are ISO 8601, `limit` sits between 1 and 100 inclusive, `offset` is at least 0, and a subdivision `children` array carries at least two entries — otherwise `ERR_INVALID_REQUEST` (400).
5. Path-templated identifiers resolve, left to right — otherwise the matching 404: `ERR_ASSOCIATION_NOT_FOUND`, `ERR_ROAD_SEGMENT_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_ROLL_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_BALLOT_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_DELINQUENCY_ACTION_NOT_FOUND`, or `ERR_CONNECTION_REQUEST_NOT_FOUND`.
6. Foreign keys supplied in the body resolve — `association_id`, `road_segment_id`, `parcel_id`, `member_id`, `proposal_id`, and `bid_id` — otherwise `ERR_ASSOCIATION_NOT_FOUND`, `ERR_ROAD_SEGMENT_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, or `ERR_BID_NOT_FOUND` respectively. This applies when recording a road segment, enrolling a parcel, adding a member, opening an assessment roll, drafting a proposal, casting a ballot, opening a maintenance project, awarding a project, and filing a connection request.
7. Ownership for the two identity-bearing roles, as described in §2.1 — otherwise `ERR_NOT_RESOURCE_OWNER` (403). This applies to ballot casting, ballot revocation, charge payment, connection-request filing, and bid withdrawal.
8. Segregation of duties on `X-User-ID` — otherwise `ERR_SEGREGATION_OF_DUTIES` (403). This applies to project award and remedy effectuation.
9. `expected_project_version` matches the project's `version` — otherwise `ERR_STALE_PROJECT_VERSION` (412), on bid submission.
10. `expected_proposal_version` matches the proposal's `version` — otherwise `ERR_STALE_PROPOSAL_VERSION` (412), on ballot casting and ballot revocation.
11. `expected_parcel_version` matches the parcel's `version` — otherwise `ERR_STALE_PARCEL_VERSION` (412), on parcel reclassification.
12. The roll is `DRAFT` for certification — otherwise `ERR_ROLL_NOT_DRAFT` (409).
13. The roll is `CERTIFIED` for recall and for levy — otherwise `ERR_ROLL_NOT_CERTIFIED` (409).
14. No roll of the parcel's association is `CERTIFIED`, for reclassification and subdivision — otherwise `ERR_CERTIFIED_ROLL_LOCKED` (409).
15. The parcel is `ACTIVE` for reclassification and subdivision, and `PENDING_CONNECTION` for connection filing and connection decisions — otherwise `ERR_PARCEL_NOT_ACTIVE` (409).
16. The member's `standing_status` is `PENDING_DEED_VERIFICATION` for deed verification — otherwise `ERR_MEMBER_ALREADY_VERIFIED` (409).
17. The charge's `status` is `OPEN`, `DELINQUENT`, or `LIEN_ENCUMBERED` and its `balance_cents` is greater than zero — otherwise `ERR_CHARGE_NOT_COLLECTIBLE` (409). This applies to payment, remedy initiation, and remedy effectuation.
18. The proposal is `DRAFT` for opening balloting — otherwise `ERR_PROPOSAL_NOT_DRAFT` (409).
19. The proposal is `BALLOTING` for ballot casting, ballot revocation, and tally — otherwise `ERR_PROPOSAL_NOT_BALLOTING` (409).
20. A `proposal_id` cited when a project is opened refers to a proposal whose `status` is `ADOPTED` — otherwise `ERR_PROPOSAL_NOT_ADOPTED` (409).
21. The ballot's `status` is `CAST` for revocation — otherwise `ERR_BALLOT_NOT_CAST` (409).
22. The project's `status` is `BID_SOLICITATION` for bid submission and for award — otherwise `ERR_PROJECT_NOT_IN_SOLICITATION` (409).
23. The project's `status` is `AWARDED` for completion — otherwise `ERR_PROJECT_NOT_AWARDED` (409).
24. The bid's `status` is `SUBMITTED` or `AWARDED` for withdrawal, and exactly `SUBMITTED` for award — otherwise `ERR_BID_NOT_ACTIVE` (409).
25. The remedy's `status` is `INITIATED` for effectuation — otherwise `ERR_ACTION_NOT_INITIATED` (409).
26. The remedy's `status` is `INITIATED` or `EFFECTIVE` for release — otherwise `ERR_ACTION_ALREADY_CLOSED` (409).
27. The connection request's `status` is `SUBMITTED` for a decision, with a denial additionally accepted from `DISPUTED`, and `DISPUTED` for dispute resolution — otherwise `ERR_REQUEST_NOT_PENDING` (409).
28. The emergency-vehicle access standard, at the strictnesses given in §2.7 — otherwise `ERR_EMERGENCY_ACCESS_DEFICIENT` (409), on project award, remedy effectuation, and connection decision.
29. The bid being awarded has `bond_on_file` true — otherwise `ERR_BOND_NOT_ON_FILE` (409).
30. `verified_deed_book_page` equals both the member's `deed_book_page` and the parcel's `deed_book_page` — otherwise `ERR_DEED_MISMATCH` (409).
31. Every `ACTIVE` covenant-recorded parcel of the association has a member whose `standing_status` is something other than `PENDING_DEED_VERIFICATION`, at certification — otherwise `ERR_MEMBERSHIP_ROLL_INCOMPLETE` (409).
32. The parcel named by a connection request has `covenant_recorded` false and a non-null `parent_parcel_id`, and a member exists on the parent parcel whose `standing_status` is something other than `PENDING_DEED_VERIFICATION` — otherwise `ERR_PARENT_MEMBER_NOT_FOUND` (409), on connection filing and connection decision.
33. The connection request's `easement_grant_recorded` is true, at approval — otherwise `ERR_EASEMENT_NOT_RECORDED` (409).
34. A parcel carries at most one member row — otherwise `ERR_DUPLICATE_MEMBER_FOR_PARCEL` (409).
35. The parcel's `covenant_recorded` is true when a membership is enrolled against it or a ballot is voted with it — otherwise `ERR_COVENANT_NOT_RECORDED` (409).
36. The awarded bid's `project_id` equals the project identifier in the path — otherwise `ERR_BID_PROJECT_MISMATCH` (409).
37. When a `proposal_id` is supplied at project creation, that proposal's `road_segment_id` equals the project's `road_segment_id` and its `project_type` equals the project's `category` — otherwise `ERR_PROPOSAL_SEGMENT_MISMATCH` (409).
38. The assessable parcel set is non-empty, meaning `total_share_units` would be greater than zero — otherwise `ERR_NO_ASSESSABLE_PARCELS` (409), at certification.
39. The children's `frontage_feet` sum exactly to the parent parcel's `frontage_feet` — otherwise `ERR_FRONTAGE_MISMATCH` (422).
40. The supplied `bid_id` is the lowest responsive bid — otherwise `ERR_NOT_LOWEST_RESPONSIVE_BID` (409).
41. A bid of at least one million cents requires at least three responsive submitted bids on the project — otherwise `ERR_INSUFFICIENT_BIDS` (409).
42. No other roll of the association shares this `fiscal_year` — otherwise `ERR_FISCAL_YEAR_ROLL_EXISTS` (409).
43. The roll's fiscal interval does not overlap another roll's interval — otherwise `ERR_FISCAL_INTERVAL_OVERLAP` (409).
44. The project's work window does not intersect another non-terminal window on the same segment — otherwise `ERR_WORK_WINDOW_CONFLICT` (409).
45. The project's window respects the paving cure buffer — otherwise `ERR_PAVING_CURE_BUFFER_VIOLATION` (409).
46. The logical clock has reached `balloting_closes_at` for a tally — otherwise `ERR_BALLOTING_STILL_OPEN` (409).
47. The logical clock is still before `balloting_closes_at` for a cast or a revocation — otherwise `ERR_BALLOTING_CLOSED` (409).
48. The logical clock date has reached the charge's `due_date` plus the thirty grace days — otherwise `ERR_CHARGE_NOT_YET_DELINQUENT` (409).
49. Date ranges are well formed: restriction dates are present for an `ACCESS_RESTRICTION` and form a half-open interval whose start precedes its end and which lies inside the fiscal interval of the charge's roll; `balloting_closes_at` is after the current clock; `completed_at` is not before the project's `window_start_date`; and a roll's `fy_start_date` precedes its `fy_end_date` — otherwise `ERR_INVALID_DATE_RANGE` (422). This applies to remedy initiation, opening balloting, project creation, and project completion.
50. The member's `restricted_days_used` plus this remedy's `restriction_days` is no more than forty-five days in the fiscal year — otherwise `ERR_RESTRICTION_DAYS_EXCEEDED` (409).
51. The voting member's `standing_status` is `GOOD_STANDING` — otherwise `ERR_MEMBER_NOT_IN_GOOD_STANDING` (409).
52. The parcel has no charge whose `status` is `OPEN`, `DELINQUENT`, or `LIEN_ENCUMBERED`, at subdivision — otherwise `ERR_PARCEL_HAS_OPEN_CHARGES` (409).
53. A payment's `amount_cents` is no more than the charge's `balance_cents` — otherwise `ERR_OVERPAYMENT` (422).
54. The charge's `balance_cents` is at least fifty thousand cents before an `ACCESS_RESTRICTION` takes effect — otherwise `ERR_BALANCE_BELOW_RESTRICTION_MINIMUM` (409).
55. A `CULVERT` or `BRIDGE` project is not awarded while the association's `reserve_posture` is `UNDERFUNDED` unless its `proposal_id` references an `ADOPTED` proposal — otherwise `ERR_RESERVE_UNDERFUNDED` (409).
56. The computed reserve draw is no more than the association's `reserve_balance_cents` — otherwise `ERR_INSUFFICIENT_RESERVE` (409).

## 3. Business Logic & Workflows

### 3.1. Standing Up the Association and Its Road Network

An `AssociationSecretary` brings the association into existence by supplying its legal `name` and a `reserve_target_cents` of at least 1. Four governance settings may be supplied at the same time, and each has a default if the request omits it. `default_voting_basis` is either `PER_PARCEL` or `ASSESSED_SHARE` and defaults to `PER_PARCEL`; it is inherited by any new proposal that does not name a basis of its own. `delinquency_interest_basis` is either `STATUTORY` or `ASSOCIATION_POLICY` and defaults to `STATUTORY`; it selects which interest branch a lien payoff quote follows. `quorum_bps` is the participation quorum in basis points, must lie between 1 and 10000, and defaults to 5000 — a bare majority of eligible weight. The freshly created association starts with an empty reserve, as described in §2.6.

The `RoadCommissioner` then records the maintained segments. A segment is created with the owning `association_id`, its covenant `name`, its centreline `length_feet` and travelway `width_feet` (both strictly greater than zero), its steepest sustained `max_grade_pct` (not negative), its `surface_type`, its `turnout_count` and `culvert_count` (neither negative), and the two structural flags `turnaround_present` and `bridge_present`. A `bridge_load_rating_tons` may be supplied and is null on a segment carrying no bridge. On creation, `required_turnouts` is derived from the length as described in §2.7, `emergency_access_grade` is set to `UNKNOWN`, and `last_inspection_at` is null.

Recording an access inspection is how the road's compliance grade actually gets set, and it is a heavier operation than it looks. The `RoadCommissioner` submits an `inspected_at` instant together with the measured geometry: `measured_width_feet`, `measured_max_grade_pct`, `measured_turnout_count`, `turnaround_present`, and optionally `measured_bridge_load_rating_tons`. Those measurements overwrite the segment's `width_feet`, `max_grade_pct`, `turnout_count`, `turnaround_present`, and `bridge_load_rating_tons` respectively, `last_inspection_at` is set to the supplied `inspected_at`, and the segment is regraded against the five-part standard. Should the regrade land on `DEFICIENT`, a cascade follows: every maintenance project on that segment whose `category` is `PAVING` and whose `status` is `BID_SOLICITATION` or `AWARDED` is moved to `CANCELLED`; because those projects cancelled, their `SUBMITTED` and `AWARDED` bids are moved to `REJECTED` and each cancelled project's `reserve_draw_cents` is returned to the association's `reserve_balance_cents` and then zeroed; because the reserve balance rose, `reserve_funding_ratio` and `reserve_posture` are recomputed and every `DRAFT` proposal's `required_threshold_bps` follows. The segment's own `version` increments by one. Segments may be listed with an optional `association_id` filter and an optional `emergency_access_grade` filter.

### 3.2. The Parcel Record: Enrollment, Reclassification, and Subdivision

A parcel is the unit of assessment. The `AssociationSecretary` enrolls one by naming the `road_segment_id` it takes access from, the recorded `deed_book_page` that carries the road-maintenance covenant, the deeded `frontage_feet` (strictly greater than zero), the `usage_class`, the average daily `trips_per_day` attributed to the parcel (not negative), and the `covenant_recorded` flag. `usage_class` is one of `RESIDENTIAL_YEAR_ROUND`, `SEASONAL`, `AGRICULTURAL`, `COMMERCIAL`, or `UNDEVELOPED`. A newly enrolled parcel has `status` `ACTIVE` and a null `parent_parcel_id`.

Two share units are derived immediately on enrollment and again on every change to the parcel's fields. The usage-class multiplier is 1.00 for `RESIDENTIAL_YEAR_ROUND`, 0.60 for `SEASONAL`, 0.80 for `AGRICULTURAL`, 1.75 for `COMMERCIAL`, and 0.25 for `UNDEVELOPED`. `frontage_share_units` is the parcel's `frontage_feet` multiplied by the multiplier for its `usage_class`. `trip_share_units` is the parcel's `trips_per_day` multiplied by twenty-five, plus its `frontage_feet` multiplied by two tenths. Note the deliberate asymmetry: the trip-generation unit applies no usage-class multiplier at all, which is the whole source of divergence between the two assessment methods. Both units are kept as exact rationals, as §2.5 requires.

Reclassifying a parcel is an `AssociationSecretary` operation that takes `expected_parcel_version` plus any subset of `frontage_feet`, `usage_class`, and `trips_per_day`. Only the supplied fields are overwritten, and both share units are recomputed afterwards. Two guards protect the assessment record: the parcel must be `ACTIVE`, and no roll of the parcel's association may currently be `CERTIFIED` — a certified roll freezes parcel data until it is either recalled or levied, and an attempt made against a certified roll is rejected with `ERR_CERTIFIED_ROLL_LOCKED`. Reclassification is never retroactive: charges that already exist keep the `share_units_snapshot` and `amount_cents` they were created with. The parcel's `version` increments by one.

Subdivision splits a deeded lot. The secretary supplies `children`, an array of at least two objects, each carrying a `deed_book_page` and a `frontage_feet`. An array with fewer than two entries is a malformed request and is rejected as such; an array whose frontages do not sum exactly to the parent's `frontage_feet` is rejected with `ERR_FRONTAGE_MISMATCH`. The parent must be `ACTIVE`, no roll of its association may be `CERTIFIED`, and the parent must carry no charge whose `status` is `OPEN`, `DELINQUENT`, or `LIEN_ENCUMBERED` — an association does not let an owner subdivide out from under an unpaid assessment, and the attempt fails with `ERR_PARCEL_HAS_OPEN_CHARGES`. On success, one parcel is created per entry in `children`, each with `parent_parcel_id` pointing at the parent, `status` `PENDING_CONNECTION`, `covenant_recorded` false, `usage_class` `UNDEVELOPED`, `trips_per_day` zero, and `road_segment_id` copied from the parent; the parent moves `ACTIVE → SUBDIVIDED`, leaving the assessable set, and its `version` increments by one. The response is an object carrying `parent_parcel` and a `children` array returned in the same order as the request's entries, so a caller can address a specific new lot without depending on a creation-timestamp tie-break. Those children are invisible to assessment until a connection request is approved; they can be found by filtering the parcel list on `parent_parcel_id`, and the same list also accepts `road_segment_id` and `status` filters.

### 3.3. The Membership Roll and Deed Verification

A membership ties a deed holder to a parcel. The `AssociationSecretary` adds a roll entry by supplying the `parcel_id`, the `owner_name` of record, the `deed_book_page` the owner asserts, and the `deed_recorded_date` as an ISO 8601 calendar date. A parcel may carry at most one membership; a second attempt is rejected with `ERR_DUPLICATE_MEMBER_FOR_PARCEL`. A membership may not be attached to a parcel whose `covenant_recorded` is false, which is rejected with `ERR_COVENANT_NOT_RECORDED`. A new member starts with `standing_status` `PENDING_DEED_VERIFICATION`, `access_status` `UNRESTRICTED`, a null `deed_verified_at`, an `encumbered_principal_cents` of zero, and a `restricted_days_used` of zero.

Verification is the only exit from `PENDING_DEED_VERIFICATION`. The secretary submits a `verified_deed_book_page`, which must equal both the member's own asserted `deed_book_page` and the `deed_book_page` recorded against the parcel; any divergence is rejected with `ERR_DEED_MISMATCH`. A second attempt on an already-verified member fails with `ERR_MEMBER_ALREADY_VERIFIED`. On success the member advances `PENDING_DEED_VERIFICATION → GOOD_STANDING`, `deed_verified_at` is stamped with the current logical-clock instant, and the member's parcel becomes eligible to appear on an assessment roll.

The two standing dimensions described in §2.8 are both exposed on the member record and both usable as list filters, alongside a `parcel_id` filter. A member's ballots and a member's delinquency remedies each have their own scoped listing, the former filterable by ballot `status` and the latter by remedy `status` and `action_type`.

### 3.4. The Annual Assessment Roll: Draft, Certify, Recall, Levy

The `AssessmentClerk` opens a roll for a fiscal year by supplying the `association_id`, the `fiscal_year` label (between 2020 and 2100), the inclusive `fy_start_date` and inclusive `fy_end_date`, the `budget_requirement_cents` to be spread (at least 1), and the `method_variant`, which is either `FRONTAGE_WEIGHTED` or `TRIP_GENERATION_WEIGHTED`. Two uniqueness rules apply: no other roll of the association may already carry that `fiscal_year`, and the roll's closed fiscal interval may not overlap any existing roll's interval of that association by even one day. Intervals that merely touch — one roll ending the day before the next begins — are permitted, and `fy_start_date` must fall strictly before `fy_end_date`. A new roll has `status` `DRAFT`, all its totals at zero, and no charges yet in existence.

Certification is where the money is actually spread, and its evaluation order is pinned. First the **assessable parcel set** is computed: every parcel whose `status` is `ACTIVE`, whose `covenant_recorded` is true, whose `road_segment_id` names a segment of the roll's association, and for which a member exists on that parcel whose `standing_status` is `GOOD_STANDING`, `DELINQUENT`, or `LIEN_FILED`. Parcels that are `SUBDIVIDED`, `WITHDRAWN`, or `PENDING_CONNECTION` are excluded, as are parcels whose member is still `PENDING_DEED_VERIFICATION`. Certification also refuses to proceed unless every `ACTIVE` covenant-recorded parcel of the association has a member past deed verification, which is `ERR_MEMBERSHIP_ROLL_INCOMPLETE`.

Second, each parcel in that set contributes a share unit chosen by the roll's `method_variant`: its `frontage_share_units` under `FRONTAGE_WEIGHTED`, or its `trip_share_units` under `TRIP_GENERATION_WEIGHTED`. The sum of those units across the set becomes the roll's `total_share_units`. If that sum is zero the certification is rejected with `ERR_NO_ASSESSABLE_PARCELS`.

Third, each parcel's raw pro-rata share is the roll's `budget_requirement_cents` multiplied by that parcel's share unit and divided by `total_share_units`, held as an exact rational with no rounding yet. Fourth, each raw share is clamped between a floor of fifty thousand cents and a per-parcel cap, where the cap is forty percent of `budget_requirement_cents` with any fraction discarded downward. A parcel whose clamped value differs from its raw value is marked as clamped. Fifth and sixth, a **single** redistribution pass runs. The residual is `budget_requirement_cents` minus the sum of the clamped values. The unclamped parcels are collected, and the sum of their share units is taken. For each unclamped parcel, provided that sum of unclamped units is greater than zero, its wanted adjustment is the residual multiplied by its own share unit and divided by the sum of unclamped units; when the residual is zero or positive the adjustment actually applied is the smaller of that wanted amount and the headroom remaining below the cap, and when the residual is negative the adjustment applied is the larger of that wanted amount and the distance down to the fifty-thousand-cent floor. Clamped parcels absorb no residual and keep their clamped value. This is exactly one pass: there is no second clamping round and no fixed-point iteration, even though the cap depends on the budget, the residual depends on the clamps, and the redistribution depends on the residual.

Seventh, each parcel's post-redistribution figure is rounded half up to whole cents to become that parcel's `amount_cents`; the rounding is per parcel and never applied to a subtotal. Eighth, the roll's `total_levied_cents` is the sum of those rounded per-parcel amounts, and its `unallocated_residual_cents` is `budget_requirement_cents` minus `total_levied_cents`. That residual is recorded rather than spread, and it may legitimately be negative when the fifty-thousand-cent floor over-collected, just as it may be positive when the per-parcel cap absorbed budget.

The certification writes one charge per assessable parcel with `charge_type` `ANNUAL` and `status` `PENDING`, freezing that parcel's `share_units_snapshot` and computed `amount_cents` onto the charge, with `paid_cents` at zero, `balance_cents` equal to `amount_cents`, a null `due_date`, and a null `delinquent_since`. Each charge records its `roll_id`, `parcel_id`, and `member_id`; its `proposal_id` stays null. The roll moves `DRAFT → CERTIFIED`, `certified_at` is stamped with the current logical-clock instant, and the roll's `version` increments by one. A roll that is not `DRAFT` cannot be certified, which is `ERR_ROLL_NOT_DRAFT`.

The roll cycle is deliberately reversible. A recall, available to the `AssessmentClerk` on a `CERTIFIED` roll and taking a `recall_reason`, moves the roll `CERTIFIED → DRAFT`: every `ANNUAL` charge of that roll whose `status` is `PENDING` moves `PENDING → VOIDED` and thereby drops out of `total_levied_cents`; `total_levied_cents`, `total_share_units`, and `unallocated_residual_cents` all reset to zero; `certified_at` resets to null; and `recall_count` increases by one. No reserve money moves on a recall, because the reserve contribution is credited only at levy. The clerk may correct parcel data and certify again — each re-certification recomputes every charge from current parcel data — so a roll's history may read `DRAFT → CERTIFIED → DRAFT → CERTIFIED → LEVIED`.

Levy is reserved to the `BoardTreasurer` and is the roll's terminal step; the clerk who certified may never levy, which is the primary segregation of duties in the fiscal workflow. Levy requires the roll to be `CERTIFIED`, failing which the request is rejected with `ERR_ROLL_NOT_CERTIFIED` — the same error a recall attempt receives on a `DRAFT` or `LEVIED` roll. On levy, every `ANNUAL` charge of the roll whose `status` is `PENDING` moves `PENDING → OPEN` and is stamped with a `due_date` of the levy date plus forty-five days; `levied_at` is stamped with the current logical-clock instant and the roll's own `due_date` is set to the same date. The roll's `reserve_contribution_cents` is set to fifteen percent of `budget_requirement_cents`, rounded half up to whole cents, and that amount is credited to the association's `reserve_balance_cents`, after which `reserve_funding_ratio` and `reserve_posture` are recomputed and, because the posture may have moved, every `DRAFT` proposal of the association has `required_threshold_bps` recomputed. The roll moves `CERTIFIED → LEVIED`.

Before committing to a method, the `AssociationSecretary`, `AssessmentClerk`, or `BoardTreasurer` may run a read-only what-if against a roll's current assessable parcel set. This capability runs the full eight-step allocation under **both** method variants and mutates nothing at all — no charges, no totals, no versions. It answers with an object carrying `roll_id`, the roll's own `method_variant`, `frontage_weighted_total_cents`, `trip_generation_weighted_total_cents`, `frontage_weighted_unallocated_residual_cents`, `trip_generation_weighted_unallocated_residual_cents`, `divergent_parcel_count` — the number of parcels whose rounded amount differs between the two methods — and `max_absolute_divergence_cents`, the largest absolute per-parcel difference. The divergence is real and not cosmetic: under `FRONTAGE_WEIGHTED` the usage class drives the split and trip generation is ignored entirely, whereas under `TRIP_GENERATION_WEIGHTED` a low-traffic `COMMERCIAL` parcel pays materially less and a busy `RESIDENTIAL_YEAR_ROUND` parcel pays more, so identical parcel data produces different per-parcel amounts and a different `unallocated_residual_cents`.

Charges may be listed with filters on `roll_id`, `proposal_id`, `parcel_id`, `member_id`, `charge_type`, and `status`.

### 3.5. Special Assessments: Proposals, Balloting, and Adoption

Capital work outside the operating budget is funded by a special assessment, and a special assessment requires a vote. The `BoardTreasurer` drafts a proposal by naming the `road_segment_id` the work serves — which also scopes the eligible voter set — the `project_type`, a short `title`, the engineer's `estimated_cost_cents` (at least 1), and the `cost_allocation_method`. `project_type` is one of `GRADING`, `CULVERT`, `PAVING`, or `BRIDGE`. `cost_allocation_method` is `FRONTAGE_WEIGHTED`, `TRIP_GENERATION_WEIGHTED`, or `EQUAL_SHARE`. A `voting_basis` may be supplied as either `PER_PARCEL` or `ASSESSED_SHARE`; when the request omits it, the proposal inherits the association's `default_voting_basis`. The proposal starts in `DRAFT` with `balloting_opened_at` null, all weight totals at zero, `quorum_met` false, `failed_tally_count` zero, and `approved_amount_cents` zero.

The `required_threshold_bps` is resolved at creation and again whenever the association's `reserve_posture` changes while the proposal is still `DRAFT`. The base threshold follows the work type: five thousand basis points for `GRADING`, six thousand for `CULVERT`, six thousand six hundred and sixty-seven for `PAVING`, and seven thousand five hundred for `BRIDGE`. Five hundred basis points are added when the proposal's `estimated_cost_cents` is strictly greater than two million cents. A further five hundred are added when the association's `reserve_posture` is `UNDERFUNDED`, on the theory that a board with no reserve should need broader consent. The sum is then capped at eight thousand basis points. The `PAVING` base is deliberately six thousand six hundred and sixty-seven rather than a clean two-thirds, which means that two of three equal votes falls just short of the bar rather than just clearing it.

Opening the balloting round moves the proposal `DRAFT → BALLOTING` and takes a single `balloting_closes_at` instant, which must be strictly after the current logical clock; a closing instant already in the past is rejected with `ERR_INVALID_DATE_RANGE`. A proposal that is not `DRAFT` cannot open a round, which is `ERR_PROPOSAL_NOT_DRAFT`. Opening the round snapshots `eligible_weight_total` as the summed voting weight of the eligible voter set at that moment, stamps `balloting_opened_at`, resets `counted_weight_total`, `yes_weight_total`, `no_weight_total`, and `abstain_weight_total` to zero, sets `quorum_met` to false, and recomputes `required_threshold_bps` from the current `reserve_posture` and freezes it for this round.

The **eligible voter set** for a proposal is every member whose `standing_status` is `GOOD_STANDING` or `DELINQUENT` and whose parcel is `ACTIVE`, has `covenant_recorded` true, and sits on the proposal's `road_segment_id`. Note the asymmetry this creates: a `DELINQUENT` member sits in the quorum denominator but may not actually cast a ballot, because casting requires `GOOD_STANDING`. A `LIEN_FILED` member leaves the eligible set entirely.

Each eligible member's weight follows the proposal's `voting_basis`. Under `PER_PARCEL` the weight is one — one vote per deeded membership regardless of assessment size, so small parcels carry the same weight as large ones. Under `ASSESSED_SHARE` the weight is derived from the member's newest certified annual charge: take that member's charges whose `charge_type` is `ANNUAL` and whose `status` is anything other than `VOIDED`, and whose roll's `status` is `CERTIFIED` or `LEVIED`; rank them by the roll's `fiscal_year` descending and then by the charge's `created_at` descending; the first row wins, and the weight is that charge's `amount_cents` divided by one hundred with any fraction discarded downward, that is, the assessment in whole dollars. A member with no such charge has weight zero. The same ballots can therefore adopt a proposal under `PER_PARCEL` and fail it under `ASSESSED_SHARE`, when the yes voters happen to be the lightly assessed ones.

A `MemberOwner` casts a ballot by supplying the `proposal_id`, their own `member_id`, a `choice` of `YES`, `NO`, or `ABSTAIN`, and the `expected_proposal_version` described in §2.9. The proposal must be `BALLOTING`, the logical clock must still be strictly before `balloting_closes_at` — a cast at or after the closing instant is rejected with `ERR_BALLOTING_CLOSED` — the `member_id` must equal `X-User-ID`, the member's `standing_status` must be `GOOD_STANDING` (otherwise `ERR_MEMBER_NOT_IN_GOOD_STANDING`), and the member's parcel must have `covenant_recorded` true (otherwise `ERR_COVENANT_NOT_RECORDED`). The new ballot starts `CAST`, has `cast_at` stamped with the current logical-clock instant, and freezes its `weight_snapshot` from the weight computation above under the proposal's basis. Recasting is legal: any prior `CAST` ballot by the same member on the same proposal moves `CAST → SUPERSEDED`, and the proposal's `counted_weight_total` and choice totals are recomputed from `CAST` ballots only. The proposal's `quorum_met` is recomputed and its `version` increments by one.

Revoking is the member's other lever. It moves the ballot `CAST → REVOKED`, requires that same `expected_proposal_version`, and requires that the ballot be `CAST` (otherwise `ERR_BALLOT_NOT_CAST`), that the proposal be `BALLOTING`, that the clock still be strictly before `balloting_closes_at`, and that the ballot's `member_id` equal `X-User-ID`. On revocation the proposal's `counted_weight_total` falls by that ballot's `weight_snapshot`, the matching choice total falls by the same amount, `quorum_met` is recomputed, and the proposal's `version` increments by one. Ballots may be read individually, listed per proposal, or listed across proposals with `proposal_id`, `member_id`, and `status` filters.

`quorum_met` is recomputed on every ballot mutation and is true exactly when `counted_weight_total` multiplied by ten thousand is at least `eligible_weight_total` multiplied by the association's `quorum_bps`.

The tally closes the round and is the proposal's only branching point. It requires the proposal to be `BALLOTING` and requires the logical clock to have reached `balloting_closes_at`; a tally taken early is rejected with `ERR_BALLOTING_STILL_OPEN`. Three outcomes are possible, and they are mutually exclusive:

- **Adoption.** When `quorum_met` is true and `yes_weight_total` multiplied by ten thousand is at least `counted_weight_total` multiplied by `required_threshold_bps`, the proposal moves `BALLOTING → ADOPTED`. Its `approved_amount_cents` is frozen at `estimated_cost_cents`, and the special assessment is spread across the assessable parcels. The spread runs the same eight steps as the annual allocation with three substitutions: the budget being spread is the proposal's `estimated_cost_cents` rather than a roll's `budget_requirement_cents`; the assessable set is additionally restricted to parcels whose `road_segment_id` equals the proposal's `road_segment_id`; and each parcel's share unit is chosen by the proposal's `cost_allocation_method` — its `frontage_share_units` under `FRONTAGE_WEIGHTED`, its `trip_share_units` under `TRIP_GENERATION_WEIGHTED`, or a flat one under `EQUAL_SHARE`. The same fifty-thousand-cent floor, the same forty-percent per-parcel cap, the same single redistribution pass, and the same per-parcel round-half-up all apply. One charge is created per assessable parcel with `charge_type` `SPECIAL`, `proposal_id` set to this proposal, `status` `OPEN`, a `due_date` of the current clock date plus forty-five days, and `roll_id` set to the association's latest levied roll. That latest levied roll is selected by taking the association's rolls whose `status` is `LEVIED`, ranking them by `fiscal_year` descending and then `created_at` descending, and taking the first; if the association has no levied roll at all, the tally is rejected with `ERR_ROLL_NOT_FOUND`. Because special charges were created, each billed member's `standing_status` is re-reconciled, which changes nothing unless one of that member's charges was already delinquent.
- **Rejection.** The proposal moves `BALLOTING → REJECTED` in either of two situations: `quorum_met` is true but `yes_weight_total` multiplied by ten thousand falls short of `counted_weight_total` multiplied by `required_threshold_bps`; or `quorum_met` is false and `failed_tally_count` has already reached two. No charges are created, `approved_amount_cents` stays zero, and every `CAST` ballot stays `CAST` as the historical record of the vote.
- **Return to draft.** When `quorum_met` is false and `failed_tally_count` is still below two, the proposal moves `BALLOTING → DRAFT`. Its `failed_tally_count` increases by one; every `CAST` ballot of the proposal moves `CAST → VOIDED`; `counted_weight_total`, `yes_weight_total`, `no_weight_total`, and `abstain_weight_total` all reset to zero and `quorum_met` returns to false; and both `balloting_opened_at` and `balloting_closes_at` reset to null so that a fresh round must be explicitly opened. The third quorum failure is therefore fatal rather than another retry.

Proposals may be listed with `road_segment_id`, `status`, and `project_type` filters.

### 3.6. Collections, Payments, and Delinquency Remedies

An `ANNUAL` charge becomes collectible when its roll is levied; `SPECIAL` and `CONNECTION_FEE` charges are created already `OPEN`. A payment may be posted by the `AssessmentClerk` or by the owning `MemberOwner`, and it carries a single `amount_cents`. The charge must be `OPEN`, `DELINQUENT`, or `LIEN_ENCUMBERED` with a positive `balance_cents`, failing which the request is rejected with `ERR_CHARGE_NOT_COLLECTIBLE`; a `MemberOwner` may only pay a charge whose `member_id` equals `X-User-ID`; and the payment may not exceed the remaining `balance_cents`, an overpayment being rejected with `ERR_OVERPAYMENT`. On success the payment is added to `paid_cents`, `balance_cents` is recomputed as `amount_cents` less `paid_cents`, and the charge moves to `PAID` only when `balance_cents` has reached exactly zero — a partial payment leaves the charge where it was.

Clearing a balance unwinds the remedies attached to it. Because the charge reached `PAID`, every delinquency action on that charge whose `status` is `EFFECTIVE` moves `EFFECTIVE → RELEASED` with `released_at` stamped and its `lien_amount_cents` reset to zero; because those actions closed, the member's `standing_status` and `access_status` are re-reconciled and `encumbered_principal_cents` falls by the released lien principal. A member sitting in `DELINQUENT` or `LIEN_FILED` returns to `GOOD_STANDING` exactly when, after the mutation, no charge of theirs remains `DELINQUENT` or `LIEN_ENCUMBERED`. A member sitting in `WARNED` or `RESTRICTED` returns to `UNRESTRICTED` exactly when, after the mutation, no `EFFECTIVE` remedy remains for that member. `restricted_days_used` is not decremented by any of this.

Delinquency is initiated by the `BoardTreasurer` against a specific past-due charge. The charge must be `OPEN` or `DELINQUENT` with a positive `balance_cents`, and the current logical-clock date must have reached the charge's `due_date` plus thirty grace days — an inclusive boundary, so a remedy on exactly the thirtieth day after the due date is permitted while anything earlier is rejected with `ERR_CHARGE_NOT_YET_DELINQUENT`. The treasurer supplies an `action_type` of `NOTICE`, `LIEN_FILING`, or `ACCESS_RESTRICTION`, and for an `ACCESS_RESTRICTION` also a `restriction_start_date` and `restriction_end_date`. Those two dates form a half-open interval — the start day is restricted, the end day is not — the start must fall strictly before the end, and the whole interval must lie inside the fiscal interval of the charge's roll; violations are rejected with `ERR_INVALID_DATE_RANGE`. The remedy's `restriction_days` is the whole number of days from the start date to the end date on that half-open reading, and it is zero for the other two action types. The new remedy starts `INITIATED`, records `initiated_by_user_id` from `X-User-ID`, copies `member_id` from the charge, and has `lien_amount_cents` and `payoff_amount_cents` at zero and `release_reason` null. As a side effect of the first action against a charge, the charge moves `OPEN → DELINQUENT` and `delinquent_since` is stamped with the current clock date, and the member's `standing_status` is reconciled to `DELINQUENT`.

Effectuation is the second treasurer's act, and it is the point at which the remedy bites. It requires the remedy to be `INITIATED` (otherwise `ERR_ACTION_NOT_INITIATED`), requires `X-User-ID` to differ from `initiated_by_user_id`, and requires the charge's `balance_cents` to still be greater than zero. Three further conditions apply only to an `ACCESS_RESTRICTION`: the charge's `balance_cents` must be at least fifty thousand cents, so the association may not gate a road over a trivial arrears (otherwise `ERR_BALANCE_BELOW_RESTRICTION_MINIMUM`); the member's `restricted_days_used` plus this remedy's `restriction_days` must be no more than forty-five days for the fiscal year, an inclusive ceiling (otherwise `ERR_RESTRICTION_DAYS_EXCEEDED`); and the parcel's road segment must be graded `COMPLIANT`. Two back-to-back restrictions that merely touch at a single date are each legal on their own and can still breach the aggregate ceiling.

A successful effectuation runs a four-hop cascade. First, the remedy moves `INITIATED → EFFECTIVE`, with `effective_at` and `effectuated_by_user_id` stamped; for a `LIEN_FILING` or an `ACCESS_RESTRICTION`, `lien_amount_cents` is frozen at the charge's `balance_cents` and `payoff_amount_cents` is set to the quoted payoff. Second, because a `LIEN_FILING` or `ACCESS_RESTRICTION` became effective, the charge moves `DELINQUENT → LIEN_ENCUMBERED`; a `NOTICE` leaves the charge `DELINQUENT`. Third, because the charge became `LIEN_ENCUMBERED`, the member's `standing_status` moves to `LIEN_FILED` and `encumbered_principal_cents` rises by the frozen `lien_amount_cents`; additionally, for an `ACCESS_RESTRICTION` the member's `access_status` moves to `RESTRICTED` and `restricted_days_used` rises by that remedy's `restriction_days`, while for a `NOTICE` the member's `access_status` moves to `WARNED` and `standing_status` is left entirely alone. Fourth, because the member's `standing_status` became `LIEN_FILED`, every ballot of that member whose `status` is `CAST` on a proposal whose `status` is `BALLOTING` moves `CAST → VOIDED`, and each affected proposal has its `counted_weight_total`, its choice totals, and its `quorum_met` recomputed — which bumps that proposal's `version` and is precisely the situation the ballot version check in §2.9 exists to surface.

The payoff quote is computed once, at the moment of effectuation, and later payments never retroactively change it. Its principal is the charge's `balance_cents` frozen at that instant, and the days delinquent are the whole days from the charge's `due_date` to the current clock date. Which branch applies is a property of the association, chosen by its `delinquency_interest_basis`. Under `STATUTORY`, the payoff is the principal plus simple interest at a twelve-percent annual rate prorated by exact days over three hundred and sixty-five: multiply the principal by twelve hundredths, multiply by the days delinquent, divide by three hundred and sixty-five, round that interest half up to whole cents, and add it to the principal. Filing costs are never added on this branch. Under `ASSOCIATION_POLICY`, the twelve-thousand-five-hundred-cent lien filing cost is added to the principal first, and the sum is then compounded by whole thirty-day months at one and a quarter percent per month: take the number of whole thirty-day months in the days delinquent, discarding any partial month, raise one plus one and a quarter hundredths to that power, multiply the principal-plus-filing-cost by the result, and round half up to whole cents once at the end. Because the filing cost is inside the base and the growth steps rather than accrues, this branch quotes a higher payoff than the statutory one for the same arrears.

Release is the single endpoint that closes a remedy, and it branches on where the remedy currently stands. Both branches take a `release_reason`. From `EFFECTIVE`, the remedy moves `EFFECTIVE → RELEASED`: `released_at` is stamped, `lien_amount_cents` resets to zero, and `payoff_amount_cents` is retained as the historical quote; because the lien was released, the charge moves `LIEN_ENCUMBERED → DELINQUENT` when its `balance_cents` is still greater than zero, or `LIEN_ENCUMBERED → PAID` when the balance has reached zero; and because the charge changed, the member's `encumbered_principal_cents`, `standing_status`, and `access_status` are all recomputed, while `restricted_days_used` is left untouched. From `INITIATED`, by contrast, the remedy moves `INITIATED → VOIDED`: `released_at` and `release_reason` are stamped, `lien_amount_cents` stays zero, the charge stays `DELINQUENT` with no lien effect at all, and the member's `standing_status` is re-reconciled — falling back to `GOOD_STANDING` only if no delinquent charge of theirs remains. A remedy already `RELEASED` or `VOIDED` cannot be released again, which is `ERR_ACTION_ALREADY_CLOSED`. When the last `EFFECTIVE` remedy on a `LIEN_ENCUMBERED` charge closes and a balance remains, the charge's move back to `DELINQUENT` is what keeps the member's standing honest.

Remedies may be read individually, listed per charge, listed per member, or listed across the association with `charge_id`, `member_id`, `action_type`, and `status` filters.

### 3.7. Contracting the Work: Solicitation, Bids, Award, and Completion

The `RoadCommissioner` opens a maintenance project, and opening it opens the bid solicitation. The commissioner supplies the `road_segment_id` the work occupies, the `category`, and the half-open work window as `window_start_date` (inclusive) and `window_end_date` (exclusive); an optional `proposal_id` names the adopted special assessment funding the work, and is null for routine operating work. `category` is one of `GRADING`, `SNOW`, `DUST`, `CULVERT`, `PAVING`, or `BRIDGE`: the first three are operating work funded from the annual levy, and the last three draw on the reserve. When a `proposal_id` is supplied, that proposal must be `ADOPTED` (otherwise `ERR_PROPOSAL_NOT_ADOPTED`) and must match the project on two axes — its `road_segment_id` must equal the project's `road_segment_id` and its `project_type` must equal the project's `category` — with any mismatch rejected as `ERR_PROPOSAL_SEGMENT_MISMATCH`.

Two window rules protect the road from being occupied twice. The new half-open window may not intersect the window of any project on the same segment whose `status` is `BID_SOLICITATION` or `AWARDED`; windows that merely touch, one ending the day the next starts, are permitted, and an intersection is rejected with `ERR_WORK_WINDOW_CONFLICT`. Separately, if the segment already hosts a `PAVING` project whose `status` is `AWARDED` or `COMPLETE`, the new window must start on or after that paving project's `window_end_date` plus three days of cure buffer; starting inside that buffer is rejected with `ERR_PAVING_CURE_BUFFER_VIOLATION`. The new project starts in `BID_SOLICITATION` with `created_by_user_id` set from `X-User-ID`, a null `awarded_bid_id`, `awarded_amount_cents` and `reserve_draw_cents` at zero, and null `awarded_by_user_id`, `completed_at`, `actual_cost_cents`, and `cancellation_reason`.

A `Contractor` responds to a solicitation with a bid, supplying its `contractor_name`, a lump-sum `amount_cents` of at least 1, a `bond_on_file` flag, and the `expected_project_version` described in §2.9. The project must be in `BID_SOLICITATION`, failing which the submission is rejected with `ERR_PROJECT_NOT_IN_SOLICITATION`. The new bid starts `SUBMITTED`, records `contractor_user_id` from `X-User-ID`, and has `submitted_at` stamped with the current logical-clock instant. A firm may revise: any prior `SUBMITTED` bid on this project by the same `contractor_user_id` moves `SUBMITTED → SUPERSEDED`, so only the newest bid from each firm is responsive. The submission increments the project's `version` by one, which is exactly why the next bidder's stale version is detectable.

Award is the second commissioner's act. It takes a single `bid_id` and is subject to a long chain of conditions, evaluated in the order §2.10 gives. The project must be `BID_SOLICITATION`; `X-User-ID` must differ from the project's `created_by_user_id`; the bid's `project_id` must equal the project in the path (otherwise `ERR_BID_PROJECT_MISMATCH`); the bid's `status` must be `SUBMITTED` (otherwise `ERR_BID_NOT_ACTIVE`); the bid's `bond_on_file` must be true (otherwise `ERR_BOND_NOT_ON_FILE`); and a `PAVING` project's segment must be graded `COMPLIANT`.

The lowest-responsive-bid rule then decides whether the nominated bid is the right one. The responsive candidate set is every bid on the project whose `status` is `SUBMITTED` and whose `bond_on_file` is true; `SUPERSEDED`, `REJECTED`, and `WITHDRAWN` bids are excluded. Candidates are ranked by `amount_cents` ascending, with ties broken by `created_at` ascending and never by identifier, and the first is the winner. If the supplied `bid_id` is not that winner — or if the candidate set is empty altogether — the award is rejected with `ERR_NOT_LOWEST_RESPONSIVE_BID`. A competitive-bidding floor then applies: when the winning bid's `amount_cents` is at least one million cents, the project must carry at least three responsive candidates, and fewer than three is rejected with `ERR_INSUFFICIENT_BIDS`. The threshold is inclusive, so a bid of exactly one million cents already needs three responsive bids.

Two reserve conditions close the chain. If the project's `category` is `CULVERT` or `BRIDGE` and the association's `reserve_posture` is `UNDERFUNDED` as of the start of the award request, the project's `proposal_id` must reference an `ADOPTED` proposal; without one, the award is rejected with `ERR_RESERVE_UNDERFUNDED`. And the computed reserve draw must not exceed the association's `reserve_balance_cents`, an inclusive comparison that permits a draw equal to the whole balance and drives it to exactly zero; exceeding it is `ERR_INSUFFICIENT_RESERVE`. The draw itself is computed as follows: for the operating categories `GRADING`, `SNOW`, and `DUST` the draw is zero, because operating work is funded from the annual levy; otherwise the proposal funding is the referenced proposal's `approved_amount_cents` when the project cites a `proposal_id` whose proposal is `ADOPTED` and zero in every other case, and the draw is the awarded bid's `amount_cents` less that proposal funding, floored at zero.

A successful award moves the project `BID_SOLICITATION → AWARDED` and the nominated bid `SUBMITTED → AWARDED`; every other bid on the project whose `status` is `SUBMITTED` moves `SUBMITTED → REJECTED`. The project's `awarded_bid_id`, `awarded_amount_cents` (taken from the awarded bid's `amount_cents`), and `awarded_by_user_id` are set, and `reserve_draw_cents` is set to the computed draw. The association's `reserve_balance_cents` falls by that draw, `reserve_funding_ratio` and `reserve_posture` are recomputed, and every `DRAFT` proposal's `required_threshold_bps` follows.

The award is reversible in three different ways, and each returns the reserve money. A `Contractor` may withdraw its own bid, supplying a `withdrawal_reason`; the bid must be `SUBMITTED` or `AWARDED` and its `contractor_user_id` must equal `X-User-ID`. The bid moves to `WITHDRAWN`. If the withdrawn bid was the awarded one, the full reversion cascade runs: the project moves `AWARDED → BID_SOLICITATION`, `awarded_bid_id` returns to null, `awarded_amount_cents` returns to zero, and `awarded_by_user_id` returns to null; the prior `reserve_draw_cents` is added back to the association's `reserve_balance_cents` and the project's draw is zeroed; and because the balance rose, `reserve_funding_ratio`, `reserve_posture`, and every `DRAFT` proposal's `required_threshold_bps` are recomputed. Bids that this award had already pushed to `REJECTED` stay `REJECTED` — a new round needs fresh bids, so the project can travel `BID_SOLICITATION → AWARDED → BID_SOLICITATION → AWARDED` more than once.

Cancellation is the commissioner's version of the same reversal. It takes a `cancellation_reason`, is available while the project is `BID_SOLICITATION` or `AWARDED`, and moves the project to `CANCELLED`. Every bid on the project whose `status` is `SUBMITTED` or `AWARDED` moves to `REJECTED`; the project's `reserve_draw_cents` is added back to the association's `reserve_balance_cents` and then zeroed; and because the balance changed, the funding ratio, the posture, and every `DRAFT` proposal's threshold are recomputed. The third route is the access-inspection cascade of §3.1, which cancels paving work on a newly deficient segment on the same terms.

Completion is terminal in the other direction. The commissioner supplies a `completed_at` instant, which may not precede the project's `window_start_date` (otherwise `ERR_INVALID_DATE_RANGE`), and an `actual_cost_cents` recording the final invoiced cost. The project must be `AWARDED`, failing which the request is rejected with `ERR_PROJECT_NOT_AWARDED`. The project moves `AWARDED → COMPLETE` with both values recorded, and its `reserve_draw_cents` is retained rather than reversed, because the draw has now actually been spent. One category carries an extra consequence: on a `PAVING` project only, the segment's `surface_type` becomes `PAVED` and its `emergency_access_grade` resets to `UNKNOWN`, because a rebuilt travelway must be re-inspected before the association may again assert compliance.

Projects may be listed with `road_segment_id`, `proposal_id`, `awarded_bid_id`, `status`, and `category` filters. Bids may be read individually, listed per project, or listed across projects with `project_id` and `status` filters.

### 3.8. New-Lot Connections and Easement Disputes

A lot created by subdivision is not yet on the road. It sits in `PENDING_CONNECTION` with no covenant and no assessment, and it becomes assessable only through a connection request. Either the `AssociationSecretary` or the `MemberOwner` of the parent parcel may file one, supplying the `parcel_id` of the new lot, the `requested_usage_class` the lot will be assessed under, the `requested_trips_per_day` it will be credited with, and an `easement_grant_recorded` flag stating whether the access easement over the private road has been recorded. The named parcel must be `PENDING_CONNECTION`, must have `covenant_recorded` false, and must carry a non-null `parent_parcel_id`; a member must exist on that parent parcel whose `standing_status` is past `PENDING_DEED_VERIFICATION`, since that member is who the connection fee will be billed to. A request naming a parcel with no subdivision parent, or a parent with no verified member, is rejected with `ERR_PARENT_MEMBER_NOT_FOUND`. A `MemberOwner` filing the request must be that parent member. The new request starts `SUBMITTED` with `connection_fee_cents` and `reserve_buyin_cents` at zero, and null `dispute_reason`, `resolution_note`, `decided_at`, and `decided_by_user_id`. No fee is computed until approval.

The secretary decides the request by supplying an `outcome`, optionally with a `dispute_reason`. Three outcomes are available, and the outcome drives which branch of the request's lifecycle runs.

Deferring into a dispute moves the request `SUBMITTED → DISPUTED` and requires a `dispute_reason` to be present; a deferral without one is rejected as a malformed request. The reason is recorded, the lot stays `PENDING_CONNECTION`, and no fee is computed. Resolving the dispute is a separate act that moves the request `DISPUTED → SUBMITTED`, requires the request to actually be `DISPUTED`, and takes a fresh `easement_grant_recorded` value and a `resolution_note`. The supplied flag overwrites the request's `easement_grant_recorded`, the `resolution_note` is recorded, and `dispute_reason` returns to null, leaving the request ready for a fresh decision — so a request may legitimately travel `SUBMITTED → DISPUTED → SUBMITTED → APPROVED`.

Denial moves the request to `DENIED` and is accepted from either `SUBMITTED` or `DISPUTED`. It stamps `decided_at` with the current logical-clock instant and `decided_by_user_id` with `X-User-ID`, and it produces no fee, no charge, and no reserve movement. Because the connection was refused, the lot's parcel moves `PENDING_CONNECTION → WITHDRAWN` and never enters the assessable set.

Approval is accepted only from `SUBMITTED` and carries the heaviest cascade in the system. Beyond the parcel and parent-member conditions above, it requires the request's `easement_grant_recorded` to be true (otherwise `ERR_EASEMENT_NOT_RECORDED`), requires the lot's road segment not to be graded `DEFICIENT`, and requires the association to have at least one roll whose `status` is `LEVIED` to hang the fee charge on — no levied roll means `ERR_ROLL_NOT_FOUND`.

The fee itself has four components, and each is rounded half up to whole cents on its own before the four integers are added; summing the exact components and rounding once at the end is a different and wrong answer, because the halves of the frontage and trip components can add to a whole cent. The base component is a flat two hundred and fifty thousand cents. The frontage component is the lot's `frontage_feet` multiplied by one thousand eight hundred and seventy-five cents per foot. The trip component is the request's `requested_trips_per_day` multiplied by forty-one thousand seven hundred and thirty-three cents. The reserve buy-in component makes the new lot pay its share of the reserve shortfall: take the association's `reserve_target_cents` less its `reserve_balance_cents`, floored at zero, to get the deficit; take the new lot's frontage share units, being its `frontage_feet` multiplied by the usage-class multiplier for the `requested_usage_class`; take the current total frontage share units of the association, being the sum of `frontage_share_units` over every parcel that is `ACTIVE` with `covenant_recorded` true on a segment of this association — a set which excludes both the `SUBDIVIDED` parent and the connecting lot itself; and multiply thirty-five hundredths by the deficit and by the new lot's units, then divide by that association total. Should the association total be zero, the reserve component is zero. The rounded reserve component becomes the request's `reserve_buyin_cents`, and the request's `connection_fee_cents` is the sum of all four rounded components.

The approval cascade then runs in four hops. First, the request moves `SUBMITTED → APPROVED`, `connection_fee_cents` and `reserve_buyin_cents` are written, and `decided_at` and `decided_by_user_id` are stamped. Second, because the request was approved, the lot's parcel moves `PENDING_CONNECTION → ACTIVE`, its `covenant_recorded` becomes true, its `usage_class` and `trips_per_day` are taken from the request's `requested_usage_class` and `requested_trips_per_day`, and both of its share units are recomputed. Third, because a fee was assessed, a charge is created with `charge_type` `CONNECTION_FEE`, `roll_id` set to the association's latest levied roll under the same ranking used for special assessments, `parcel_id` set to the new lot, `member_id` set to the parent parcel's member — the new owner has no membership yet, so the parent is billed — `status` `OPEN`, and a `due_date` of the current clock date plus forty-five days. Fourth, because `reserve_buyin_cents` was credited, the association's `reserve_balance_cents` rises by that amount, `reserve_funding_ratio` and `reserve_posture` are recomputed, and every `DRAFT` proposal's `required_threshold_bps` follows.

Connection requests may be read individually, listed for a single lot, or listed across lots with `parcel_id` and `status` filters.

## 4. Endpoint Definitions

Operations that bring a new, independently addressable resource into existence — registering an association, recording a segment, enrolling a parcel, adding a member, opening a roll, drafting a proposal, casting a ballot, opening a project, submitting a bid, initiating a delinquency remedy, or filing a connection request — return `201 Created`. Every other successful operation, including all state transitions, all reclassifications, all reads, the subdivision of an existing parcel, and the logical-clock capability, returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/associations` | Register the private road association and its reserve target | AssociationSecretary |
| GET | `/associations/{association_id}` | Read the association including its live reserve balance, funding ratio and posture | AssociationSecretary, AssessmentClerk, BoardTreasurer, RoadCommissioner, MemberOwner |
| POST | `/road-segments` | Add a maintained segment | RoadCommissioner |
| GET | `/road-segments/{segment_id}` | Read one segment | AssociationSecretary, AssessmentClerk, BoardTreasurer, RoadCommissioner, MemberOwner |
| GET | `/road-segments` | List segments, filterable by association and access grade | AssociationSecretary, AssessmentClerk, BoardTreasurer, RoadCommissioner, MemberOwner |
| POST | `/road-segments/{segment_id}/access-inspections` | Record an emergency-vehicle access inspection and regrade the segment | RoadCommissioner |
| POST | `/parcels` | Enroll a deeded parcel on a segment | AssociationSecretary |
| GET | `/parcels/{parcel_id}` | Read one parcel including both share-unit values | AssociationSecretary, AssessmentClerk, BoardTreasurer, RoadCommissioner, MemberOwner |
| GET | `/parcels` | List parcels, filterable by segment, subdivision parent or status | AssociationSecretary, AssessmentClerk, BoardTreasurer, RoadCommissioner, MemberOwner |
| PATCH | `/parcels/{parcel_id}` | Reclassify a parcel's frontage, usage class or trip generation | AssociationSecretary |
| POST | `/parcels/{parcel_id}/subdivide` | Split a deeded parcel into lots | AssociationSecretary |
| POST | `/members` | Add a membership roll entry tied to a parcel deed | AssociationSecretary |
| GET | `/members/{member_id}` | Read one member including both state dimensions and the restriction-day counter | AssociationSecretary, AssessmentClerk, BoardTreasurer, RoadCommissioner, MemberOwner |
| GET | `/members` | List members, filterable by parcel or by either state dimension | AssociationSecretary, AssessmentClerk, BoardTreasurer, RoadCommissioner, MemberOwner |
| POST | `/members/{member_id}/verify-deed` | Verify the recorded deed and admit the member to good standing | AssociationSecretary |
| GET | `/members/{member_id}/ballots` | List every ballot cast by a member | AssociationSecretary, BoardTreasurer, MemberOwner |
| GET | `/members/{member_id}/delinquency-actions` | List every delinquency remedy against a member | AssociationSecretary, AssessmentClerk, BoardTreasurer, MemberOwner |
| POST | `/assessment-rolls` | Open a draft annual assessment roll for a fiscal year | AssessmentClerk |
| GET | `/assessment-rolls/{roll_id}` | Read one roll including its levied total and unallocated residual | AssociationSecretary, AssessmentClerk, BoardTreasurer, RoadCommissioner, MemberOwner |
| GET | `/assessment-rolls` | List rolls, ordered by fiscal year then creation | AssociationSecretary, AssessmentClerk, BoardTreasurer, RoadCommissioner, MemberOwner |
| GET | `/assessment-rolls/{roll_id}/method-comparison` | Read-only what-if reporting the divergence between the two allocation methods | AssociationSecretary, AssessmentClerk, BoardTreasurer |
| POST | `/assessment-rolls/{roll_id}/certify` | Certify the roll, spreading the budget and creating pending charges | AssessmentClerk |
| POST | `/assessment-rolls/{roll_id}/recall` | Recall a certified roll to draft, voiding its charges | AssessmentClerk |
| POST | `/assessment-rolls/{roll_id}/levy` | Levy the certified roll and credit the reserve contribution | BoardTreasurer |
| GET | `/assessment-charges/{charge_id}` | Read one charge including balance and collection status | AssociationSecretary, AssessmentClerk, BoardTreasurer, MemberOwner |
| GET | `/assessment-charges` | List charges, filterable by roll, proposal, parcel, member, type or status | AssociationSecretary, AssessmentClerk, BoardTreasurer, MemberOwner |
| POST | `/assessment-charges/{charge_id}/payments` | Apply a payment to a collectible charge | MemberOwner, AssessmentClerk |
| GET | `/assessment-charges/{charge_id}/delinquency-actions` | List every remedy pursued against a charge | AssociationSecretary, AssessmentClerk, BoardTreasurer, MemberOwner |
| POST | `/assessment-charges/{charge_id}/delinquency-actions` | Initiate a delinquency remedy on a past-due charge | BoardTreasurer |
| GET | `/delinquency-actions` | List remedies across charges | AssociationSecretary, AssessmentClerk, BoardTreasurer, MemberOwner |
| GET | `/delinquency-actions/{action_id}` | Read one remedy including its frozen lien and payoff figures | AssociationSecretary, AssessmentClerk, BoardTreasurer, MemberOwner |
| POST | `/delinquency-actions/{action_id}/effectuate` | Effectuate an initiated remedy | BoardTreasurer |
| POST | `/delinquency-actions/{action_id}/release` | Release an effective remedy, or void one never effectuated | BoardTreasurer |
| POST | `/special-assessment-proposals` | Draft a special assessment proposal for capital work | BoardTreasurer |
| GET | `/special-assessment-proposals/{proposal_id}` | Read one proposal including live tally totals and quorum state | AssociationSecretary, AssessmentClerk, BoardTreasurer, RoadCommissioner, MemberOwner |
| GET | `/special-assessment-proposals` | List proposals, filterable by segment, status or project type | AssociationSecretary, AssessmentClerk, BoardTreasurer, RoadCommissioner, MemberOwner |
| POST | `/special-assessment-proposals/{proposal_id}/open-balloting` | Open the balloting round and snapshot the eligible voting weight | BoardTreasurer |
| POST | `/special-assessment-proposals/{proposal_id}/tally` | Close the round and branch to adoption, rejection or back to draft | BoardTreasurer |
| GET | `/special-assessment-proposals/{proposal_id}/ballots` | List every ballot on a proposal | AssociationSecretary, BoardTreasurer, MemberOwner |
| POST | `/ballots` | Cast or recast a ballot | MemberOwner |
| GET | `/ballots/{ballot_id}` | Read one ballot including its frozen weight snapshot | AssociationSecretary, BoardTreasurer, MemberOwner |
| GET | `/ballots` | List ballots across proposals | AssociationSecretary, BoardTreasurer, MemberOwner |
| POST | `/ballots/{ballot_id}/revoke` | Revoke a cast ballot before the round closes | MemberOwner |
| POST | `/maintenance-projects` | Open a maintenance project and its bid solicitation | RoadCommissioner |
| GET | `/maintenance-projects/{project_id}` | Read one project including awarded amount and reserve draw | AssociationSecretary, AssessmentClerk, BoardTreasurer, RoadCommissioner, MemberOwner, Contractor |
| GET | `/maintenance-projects` | List projects, filterable by segment, proposal, awarded bid, status or category | AssociationSecretary, AssessmentClerk, BoardTreasurer, RoadCommissioner, MemberOwner, Contractor |
| POST | `/maintenance-projects/{project_id}/contractor-bids` | Submit a bid under optimistic concurrency on the project's version | Contractor |
| GET | `/maintenance-projects/{project_id}/contractor-bids` | List every bid on a project | AssociationSecretary, BoardTreasurer, RoadCommissioner, Contractor |
| POST | `/maintenance-projects/{project_id}/award` | Award the lowest responsive bid and hold the reserve draw | RoadCommissioner |
| POST | `/maintenance-projects/{project_id}/complete` | Record completion and the invoiced cost | RoadCommissioner |
| POST | `/maintenance-projects/{project_id}/cancel` | Cancel a solicitation or an award, returning any reserve draw | RoadCommissioner |
| GET | `/contractor-bids/{bid_id}` | Read one bid including its responsiveness flags and status | AssociationSecretary, BoardTreasurer, RoadCommissioner, Contractor |
| GET | `/contractor-bids` | List bids across projects | AssociationSecretary, BoardTreasurer, RoadCommissioner, Contractor |
| POST | `/contractor-bids/{bid_id}/withdraw` | Withdraw an own bid | Contractor |
| POST | `/connection-requests` | Apply to connect a newly subdivided lot to the private road | MemberOwner, AssociationSecretary |
| GET | `/connection-requests/{request_id}` | Read one connection request including the fee and reserve buy-in | AssociationSecretary, AssessmentClerk, BoardTreasurer, MemberOwner |
| GET | `/connection-requests` | List connection requests across lots | AssociationSecretary, AssessmentClerk, BoardTreasurer, MemberOwner |
| GET | `/parcels/{parcel_id}/connection-requests` | List connection requests for a lot | AssociationSecretary, AssessmentClerk, BoardTreasurer, MemberOwner |
| POST | `/connection-requests/{request_id}/decide` | Approve, deny, or defer the request into an easement dispute | AssociationSecretary |
| POST | `/connection-requests/{request_id}/resolve-dispute` | Record the easement resolution and return the request for a fresh decision | AssociationSecretary |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | AssociationSecretary, AssessmentClerk, BoardTreasurer, RoadCommissioner |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_ASSOCIATION_NOT_FOUND` | 404 |
| `ERR_ROAD_SEGMENT_NOT_FOUND` | 404 |
| `ERR_PARCEL_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_ROLL_NOT_FOUND` | 404 |
| `ERR_CHARGE_NOT_FOUND` | 404 |
| `ERR_PROPOSAL_NOT_FOUND` | 404 |
| `ERR_BALLOT_NOT_FOUND` | 404 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_BID_NOT_FOUND` | 404 |
| `ERR_DELINQUENCY_ACTION_NOT_FOUND` | 404 |
| `ERR_CONNECTION_REQUEST_NOT_FOUND` | 404 |
| `ERR_STALE_PROJECT_VERSION` | 412 |
| `ERR_STALE_PROPOSAL_VERSION` | 412 |
| `ERR_STALE_PARCEL_VERSION` | 412 |
| `ERR_ROLL_NOT_DRAFT` | 409 |
| `ERR_ROLL_NOT_CERTIFIED` | 409 |
| `ERR_CERTIFIED_ROLL_LOCKED` | 409 |
| `ERR_PARCEL_NOT_ACTIVE` | 409 |
| `ERR_MEMBER_ALREADY_VERIFIED` | 409 |
| `ERR_CHARGE_NOT_COLLECTIBLE` | 409 |
| `ERR_PROPOSAL_NOT_DRAFT` | 409 |
| `ERR_PROPOSAL_NOT_BALLOTING` | 409 |
| `ERR_PROPOSAL_NOT_ADOPTED` | 409 |
| `ERR_BALLOT_NOT_CAST` | 409 |
| `ERR_PROJECT_NOT_IN_SOLICITATION` | 409 |
| `ERR_PROJECT_NOT_AWARDED` | 409 |
| `ERR_BID_NOT_ACTIVE` | 409 |
| `ERR_ACTION_NOT_INITIATED` | 409 |
| `ERR_ACTION_ALREADY_CLOSED` | 409 |
| `ERR_REQUEST_NOT_PENDING` | 409 |
| `ERR_EMERGENCY_ACCESS_DEFICIENT` | 409 |
| `ERR_BOND_NOT_ON_FILE` | 409 |
| `ERR_DEED_MISMATCH` | 409 |
| `ERR_MEMBERSHIP_ROLL_INCOMPLETE` | 409 |
| `ERR_PARENT_MEMBER_NOT_FOUND` | 409 |
| `ERR_EASEMENT_NOT_RECORDED` | 409 |
| `ERR_DUPLICATE_MEMBER_FOR_PARCEL` | 409 |
| `ERR_COVENANT_NOT_RECORDED` | 409 |
| `ERR_BID_PROJECT_MISMATCH` | 409 |
| `ERR_PROPOSAL_SEGMENT_MISMATCH` | 409 |
| `ERR_NO_ASSESSABLE_PARCELS` | 409 |
| `ERR_FRONTAGE_MISMATCH` | 422 |
| `ERR_NOT_LOWEST_RESPONSIVE_BID` | 409 |
| `ERR_INSUFFICIENT_BIDS` | 409 |
| `ERR_FISCAL_YEAR_ROLL_EXISTS` | 409 |
| `ERR_FISCAL_INTERVAL_OVERLAP` | 409 |
| `ERR_WORK_WINDOW_CONFLICT` | 409 |
| `ERR_PAVING_CURE_BUFFER_VIOLATION` | 409 |
| `ERR_BALLOTING_STILL_OPEN` | 409 |
| `ERR_BALLOTING_CLOSED` | 409 |
| `ERR_CHARGE_NOT_YET_DELINQUENT` | 409 |
| `ERR_RESTRICTION_DAYS_EXCEEDED` | 409 |
| `ERR_MEMBER_NOT_IN_GOOD_STANDING` | 409 |
| `ERR_PARCEL_HAS_OPEN_CHARGES` | 409 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_BALANCE_BELOW_RESTRICTION_MINIMUM` | 409 |
| `ERR_RESERVE_UNDERFUNDED` | 409 |
| `ERR_INSUFFICIENT_RESERVE` | 409 |
