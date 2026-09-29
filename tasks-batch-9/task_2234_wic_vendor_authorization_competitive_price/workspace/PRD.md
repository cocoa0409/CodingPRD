# WIC Vendor Authorization & Competitive Price Management API — Product Requirements Document

## 1. Introduction

State WIC agencies sit between two obligations that pull in opposite directions. They must keep enough authorized retail vendors on the map that participants can actually redeem their benefits, and they must simultaneously guarantee that every dollar of federal food money leaves the agency at a competitive price, against a stocked shelf, in a store that has not been quietly overcharging. Today the vendor unit does that reconciliation by hand: peer groups live in a spreadsheet, shelf-price surveys arrive by fax, maximum allowable reimbursement is recalculated by an analyst with a calculator, and the sanction schedule is applied from memory. The consequence is uneven treatment across vendors, ceilings that lag the market by a full price cycle, and disqualifications that cannot survive an administrative appeal because nobody can reconstruct how the tier was reached.

This document specifies the API for the state WIC vendor unit's authorization and competitive price management platform. It covers the full arc of the vendor relationship: intake and peer group assignment by store type and redemption volume; the competitive price cycle in which vendors report shelf prices and the agency derives a maximum allowable reimbursement per item per peer group; minimum stock verification at monitoring visits; the authorized food list and its mapping to UPC catalogs with infant formula restrictions; transaction edits that reject or reduce claim lines and the reimbursement adjustments that recoup overpayments; high-risk vendor identification and compliance buys; and the sanction schedule with its fork between a civil money penalty and disqualification, plus the training and reauthorization cycle that keeps an authorized vendor authorized.

Two engineering constraints shape everything below. First, the system is a **compliance record**, not merely a workflow tool: every computed number a vendor could contest — a ceiling, an edit code, a recoupment share, a penalty tier — must be reproducible from stored inputs, which is why this document pins evaluation order, tie-breaks, and rounding points rather than leaving them to implementation taste. Second, the vendor unit operates under **segregation of duties**: the analyst who raises a recoupment may not release it, and the investigator who opens a sanction case may not impose its disqualification. Those separations are enforced by the server, not by policy documents.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across every endpoint. Where §3 describes what a workflow means, §2 describes how every request is framed, ordered, and rejected.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which it acts. If either header is absent, or if `X-User-Role` is not one of the five declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are well-formed but the declared role is not among the roles authorized for the addressed endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The five roles are `VendorOperator`, `VendorUnitAnalyst`, `VendorUnitSupervisor`, `ComplianceInvestigator`, and `SystemOperator`.

- A `VendorOperator` is the retail vendor itself. It reports shelf prices, revises rejected submissions, files monthly redemption claims, and elects the civil money penalty when a sanction notice offers one. When `X-User-Role` is `VendorOperator`, `X-User-ID` is the `id` of the acting Vendor; ownership checks on any resource that references a Vendor compare that resource's vendor foreign key to `X-User-ID`. Concretely, a `VendorOperator` addressing a Vendor, PriceSubmission, RedemptionClaim, ClaimLine, or SanctionCase must be the vendor those resources belong to, and when a request body carries a `vendor_id` it must equal `X-User-ID`. A mismatch is rejected with `ERR_VENDOR_SCOPE_VIOLATION` (HTTP 403). Reads of shared reference data — food categories, authorized food list items, price cycles, and price ceilings — are not vendor-scoped.
- A `VendorUnitAnalyst` performs intake, records training, reviews shelf-price submissions, schedules and conducts monitoring visits, adjudicates claims, and may raise reimbursement adjustments. When `X-User-Role` is `VendorUnitAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it — as `reviewed_by_user_id` on a reviewed PriceSubmission and as `created_by_user_id` on a raised ReimbursementAdjustment — but never compares it to any entity's `id`.
- A `VendorUnitSupervisor` owns configuration, authorization decisions, ceiling publication, money movement, and case closure. When `X-User-Role` is `VendorUnitSupervisor`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it as `created_by_user_id` or `applied_by_user_id` on a ReimbursementAdjustment but does not compare it to any entity's `id`.
- A `ComplianceInvestigator` runs compliance buys and sanction cases. When `X-User-Role` is `ComplianceInvestigator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `opened_by_user_id` on a SanctionCase but does not compare it to any entity's `id`.
- A `SystemOperator` drives the logical clock and the periodic risk run and does nothing else. When `X-User-Role` is `SystemOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is never compared to any entity's `id`.

Two role restrictions are finer-grained than the endpoint role list. A monitoring visit whose `visit_type` is `COMPLIANCE_BUY` may only be created by a `ComplianceInvestigator`; a `VendorUnitAnalyst` may create `ROUTINE` and `HIGH_RISK_FOLLOWUP` visits only, and an attempt to create a compliance buy under any other role is rejected with `ERR_FORBIDDEN_VISIT_TYPE` (HTTP 403). Separately, the segregation-of-duties rules of §2.10 reject an otherwise-authorized actor on identity grounds with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, must be at least 1, and must not exceed 100. `offset` is the number of items to skip; it defaults to 0 and must not be negative. A `limit` outside the range from 1 to 100 inclusive, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

Unless a specific endpoint says otherwise, list results are sorted by `created_at` in ascending order.

The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in this system — PeerGroup, FoodCategory, AuthorizedFoodItem, Vendor, PriceCycle, PriceSubmission, PriceCeiling, MonitoringVisit, RedemptionClaim, ClaimLine, ReimbursementAdjustment, and SanctionCase — carries the same four system-managed properties:

- `id` (string): a server-minted UUID. It carries no type prefix; a vendor's identifier and a claim's identifier are indistinguishable by shape.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the row was first written.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the most recent mutation of the row.
- `version` (integer): a counter that increments by one on every mutation of the row.

A mutation for the purposes of `updated_at` and `version` includes changes the client did not directly request. When authorizing a vendor increments the `member_count` of its peer group, the peer group's own `version` increments and its `updated_at` refreshes. When a delisting cascade voids a price submission, that submission's `version` increments. When adjudication stamps an edit result onto a claim line, that line's `version` increments. Derived and denormalized fields are not exempt: recomputing `price_submission_complete`, `risk_score`, or `recoupment_balance_cents` on a Vendor is a mutation of the Vendor.

All list and read endpoints expose the full field set of the resource they return, including computed fields, so that a client can observe a `version` before attempting a version-guarded write.

### 2.5. The Logical Clock and Calendar-Month Arithmetic

Time in this system is a logical clock, never the host's wall clock. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server never falls back to real time. A `SystemOperator` moves the clock by supplying a `current_utc` instant, and the response echoes back the `current_utc` now in force. Every deadline, window, expiry, and "as of" evaluation described in this document reads the logical clock at the moment the request is processed.

Two kinds of date arithmetic appear, and they are not interchangeable. **Day arithmetic** — cure periods, blackout buffers, election windows, reauthorization windows, and risk windows — adds or subtracts a fixed number of 24-hour days. **Calendar-month arithmetic** — training validity, reauthorization cycles, and disqualification periods — adds a number of months by landing on the same day-of-month in the target month, clamping to the last valid day of that month when the source day does not exist there (so adding one month to January 31 yields the last day of February), and preserving the time of day exactly.

All instants persisted and returned by the API use ISO 8601 UTC with three fractional digits.

### 2.6. Cents, Percentages, and Rounding Discipline

Money is integer cents throughout. Prices, ceilings, allowed amounts, recoupments, and penalties are whole-cent integers in requests and responses; there are no fractional-cent money fields. Where a formula multiplies money by a rate, the result is rounded **half up** to a whole cent, and this document states exactly where in the formula that rounding happens, because the placement changes the answer.

Three rounding rules matter enough to state globally:

1. **One rounding, at the end.** When the maximum allowable reimbursement is derived, the intermediate base price and the statewide cap are both kept unrounded as decimals; rounding half up to a whole cent is applied exactly once, to the value finally selected. Rounding the base and then applying the allowance is not the rule.
2. **Per line first, then sum.** When a reimbursement adjustment prorates a recoupment across claim lines, each line's share is rounded half up to a whole cent individually and the shares are then added. The total is whatever that sum comes to; the residual difference against rounding the claim total once is not redistributed to any line.
3. **Percentages carry one decimal.** `stock_compliance_pct` and `risk_score` are rounded half up to one decimal place, once, at the end of their computation.

Counts are integers with no rounding. Quantity multiplied by a unit price in cents is exact and never rounded.

### 2.7. Request Rejection Order and Identifier Resolution

When a request violates more than one rule, exactly one error is returned: the one belonging to the lowest-numbered rule in the ladder below. The ladder is global — it is the reason a stale-version rejection can never be masked by a state-machine rejection, and the reason a forbidden role never learns whether the resource it addressed exists.

1. Headers present and `X-User-Role` recognized — otherwise `ERR_UNAUTHENTICATED`.
2. The acting role appears in the addressed endpoint's role list — otherwise `ERR_FORBIDDEN_ROLE`.
3. For any endpoint whose role list includes `VendorOperator`, the vendor scope check of §2.1 — otherwise `ERR_VENDOR_SCOPE_VIOLATION`.
4. On visit creation, the compliance-buy role restriction — otherwise `ERR_FORBIDDEN_VISIT_TYPE`.
5. Path identifiers resolve, **left to right**. On every path-parameterised endpoint the segments are resolved in the order they appear in the URL, and the first unresolved segment decides the error: `ERR_PEER_GROUP_NOT_FOUND`, `ERR_FOOD_CATEGORY_NOT_FOUND`, `ERR_FOOD_ITEM_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_PRICE_CYCLE_NOT_FOUND`, `ERR_PRICE_SUBMISSION_NOT_FOUND`, `ERR_PRICE_CEILING_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CLAIM_LINE_NOT_FOUND`, `ERR_ADJUSTMENT_NOT_FOUND`, or `ERR_SANCTION_CASE_NOT_FOUND`, each HTTP 404.
6. Body foreign keys resolve, in the order the endpoint's input list declares them, on `POST /authorized-food-items`, `POST /price-submissions`, `POST /monitoring-visits`, `POST /monitoring-visits/{id}/observations`, `POST /redemption-claims`, `POST /reimbursement-adjustments`, and `POST /sanction-cases`. The same 404 family applies — an unresolvable `food_item_id` yields `ERR_FOOD_ITEM_NOT_FOUND`, an unresolvable `vendor_id` yields `ERR_VENDOR_NOT_FOUND`, an unresolvable `source_visit_id` yields `ERR_VISIT_NOT_FOUND`, an unresolvable `redemption_claim_id` yields `ERR_CLAIM_NOT_FOUND`, an unresolvable `food_category_id` yields `ERR_FOOD_CATEGORY_NOT_FOUND`, and an unresolvable `price_cycle_id` yields `ERR_PRICE_CYCLE_NOT_FOUND`.
7. Request shape: required fields present, enum values in range, integers not negative, `recoupment_rate` greater than 0 and at most 1, `competitive_allowance_pct` at least 0 and at most 0.25, `lines` non-empty with no repeated `line_number`, `limit` between 1 and 100 inclusive, `offset` not negative, and `claim_month` matching a four-digit year, a hyphen, and a two-digit month from 01 through 12. Otherwise `ERR_INVALID_REQUEST` (HTTP 422).
8. Peer group `code` uniqueness on `POST /peer-groups` — otherwise `ERR_DUPLICATE_PEER_GROUP_CODE`.
9. Food category `code` uniqueness on `POST /food-categories` — otherwise `ERR_DUPLICATE_FOOD_CATEGORY_CODE`.
10. `upc` uniqueness among `ACTIVE` items on `POST /authorized-food-items` — otherwise `ERR_DUPLICATE_UPC`.
11. `cycle_code` uniqueness on `POST /price-cycles` — otherwise `ERR_DUPLICATE_CYCLE_CODE`.
12. `submission_open_at` strictly before `submission_due_at` on `POST /price-cycles` — otherwise `ERR_INVALID_CYCLE_WINDOW`.
13. Cycle window non-overlap on `POST /price-cycles` — otherwise `ERR_CYCLE_WINDOW_OVERLAP`.
14. `expected_claim_version` matches the claim's `version` on `POST /reimbursement-adjustments` — otherwise `ERR_STALE_CLAIM_VERSION`.
15. `expected_vendor_version` matches the vendor's `version` on `POST /sanction-cases` — otherwise `ERR_STALE_VENDOR_VERSION`.
16. The addressed entity is in a state that permits the requested transition, on every action endpoint. The error names the entity: `ERR_INVALID_VENDOR_STATE`, `ERR_INVALID_CYCLE_STATE`, `ERR_INVALID_SUBMISSION_STATE`, `ERR_INVALID_VISIT_STATE`, `ERR_INVALID_CLAIM_STATE`, `ERR_INVALID_ADJUSTMENT_STATE`, or `ERR_INVALID_SANCTION_STATE`, each HTTP 409.
17. On `POST /reimbursement-adjustments`, the referenced claim has left `SUBMITTED` — its `status` is `ADJUDICATED`, `ADJUSTED`, or `PAID` — otherwise `ERR_CLAIM_NOT_ADJUDICATED`.
18. On `POST /reimbursement-adjustments`, `POST /reimbursement-adjustments/{id}/apply`, and `POST /reimbursement-adjustments/{id}/reverse`, the referenced claim has not been marked paid — otherwise `ERR_CLAIM_ALREADY_PAID`.
19. On `POST /monitoring-visits`, `POST /monitoring-visits/{id}/conduct`, and `POST /redemption-claims`, the vendor is monitorable — otherwise `ERR_VENDOR_NOT_MONITORABLE`.
20. On `POST /reimbursement-adjustments/{id}/apply` and `POST /sanction-cases/{id}/impose-disqualification`, the segregation-of-duties check of §2.10 — otherwise `ERR_SEGREGATION_OF_DUTIES`.
21. On `POST /vendors/{id}/authorize` and `POST /vendors/{id}/complete-reauthorization`, training currency — otherwise `ERR_VENDOR_TRAINING_EXPIRED`.
22. On `POST /vendors/{id}/authorize`, `POST /vendors/{id}/complete-reauthorization`, and `POST /sanction-cases`, no sanction case of the vendor sits in `OPENED` or `NOTICE_SERVED` — otherwise `ERR_OPEN_SANCTION_CASE_EXISTS`.
23. On `POST /vendors/{id}/submit-application`, `POST /price-submissions`, and `POST /redemption-claims`, the vendor's disqualification period has elapsed — otherwise `ERR_VENDOR_DISQUALIFIED`.
24. On `POST /monitoring-visits`, a compliance buy is warranted — otherwise `ERR_COMPLIANCE_BUY_NOT_WARRANTED`.
25. On `POST /sanction-cases/{id}/elect-cmp`, `cmp_permitted` is true — otherwise `ERR_CMP_NOT_PERMITTED`.
26. On `POST /sanction-cases/{id}/elect-cmp`, the election window is still open — otherwise `ERR_CMP_ELECTION_WINDOW_EXPIRED`.
27. On `POST /sanction-cases/{id}/impose-disqualification`, the election window has closed or the violation is `CLASS_A` — otherwise `ERR_ELECTION_WINDOW_OPEN`.
28. On `POST /sanction-cases/{id}/impose-disqualification`, `disqualification_months` is greater than zero — otherwise `ERR_DISQUALIFICATION_NOT_AVAILABLE`.
29. On `POST /monitoring-visits`, `scheduled_for` is not earlier than the logical clock — otherwise `ERR_VISIT_DATE_IN_PAST` (HTTP 422).
30. On `POST /monitoring-visits`, the blackout buffer around `scheduled_for` is clear — otherwise `ERR_VISIT_BLACKOUT_CONFLICT`.
31. On `POST /monitoring-visits/{id}/observations`, at most one observation per visit and `food_category_id` pair — otherwise `ERR_DUPLICATE_OBSERVATION`.
32. On `POST /price-submissions` and `POST /price-submissions/{id}/revise`, the cycle's submission window is open — otherwise `ERR_SUBMISSION_WINDOW_CLOSED`.
33. On `POST /price-submissions`, no live submission already exists for the same vendor, item, and cycle — otherwise `ERR_DUPLICATE_PRICE_SUBMISSION`.
34. On `POST /price-submissions/{id}/revise`, the revision budget is not exhausted — otherwise `ERR_REVISION_LIMIT_REACHED`.
35. On `POST /vendors/{id}/authorize` and `POST /vendors/{id}/complete-reauthorization`, the vendor's assigned peer group is `ACTIVE` — otherwise `ERR_PEER_GROUP_RETIRED`.
36. On `POST /vendors/{id}/authorize` and `POST /vendors/{id}/complete-reauthorization`, `price_submission_complete` is true — otherwise `ERR_PRICE_SUBMISSIONS_INCOMPLETE`.
37. On `POST /vendors/{id}/submit-application`, a peer group matches — otherwise `ERR_NO_PEER_GROUP_MATCH` (HTTP 422).
38. On `POST /redemption-claims/{id}/adjudicate`, a published price cycle exists at or before the logical clock — otherwise `ERR_NO_PUBLISHED_PRICE_CYCLE`.
39. On `POST /vendors/{id}/complete-reauthorization`, `reauthorization_hold` is false — otherwise `ERR_REAUTHORIZATION_HOLD`.
40. On `POST /vendors/{id}/start-reauthorization`, the reauthorization window is open — otherwise `ERR_REAUTH_WINDOW_NOT_OPEN`.
41. On `POST /reimbursement-adjustments` and `POST /reimbursement-adjustments/{id}/apply`, the computed recoupment fits inside the claim's net payable amount — otherwise `ERR_RECOUPMENT_EXCEEDS_PAYABLE` (HTTP 422).
42. On `POST /sanction-cases/{id}/close`, the civil money penalty is fully paid when closing from the penalty branch — otherwise `ERR_CMP_UNDERPAID`.

The substantive meaning of rules 8 through 42 — what "warranted", "monitorable", "current", or "open" means in each case — is developed in §3 next to the workflow each rule guards. The ladder above fixes only which rejection wins.

### 2.8. Optimistic Concurrency on Parent Versions

Two write endpoints derive their result from a parent entity's current numbers, and both therefore require the client to prove it has read that parent recently. Neither uses a header; in both cases the guard is a non-optional field in the request body.

Raising a reimbursement adjustment against a redemption claim requires `expected_claim_version` in the body of a `POST /reimbursement-adjustments` request, carrying the `version` the client last observed on that RedemptionClaim. If it does not equal the claim's current `version`, the create is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412). A claim may legitimately carry several adjustments, so a second adjustment is not blocked by any state rule — but because the recoupment base is the claim's `net_payable_cents`, and because every accepted adjustment moves that base, a client that has not re-read the claim is computing against a number the server has already replaced. Note that a successful create itself increments the claim's `version` by one, so a client raising two adjustments in sequence must re-read the claim between them.

Opening a sanction case against a vendor requires `expected_vendor_version` in the body of a `POST /sanction-cases` request, carrying the `version` the client last observed on that Vendor. If it does not equal the vendor's current `version`, the create is rejected with `ERR_STALE_VENDOR_VERSION` (HTTP 412). The vendor's `sanction_points`, `risk_epoch_at`, and `open_finding_count` all feed the tier escalation computed at open time, so a case opened from a stale vendor view would be tiered on superseded data. A successful create increments the vendor's `version` by one.

No other endpoint accepts a version field. Requests to endpoints outside these two are processed without any optimistic-concurrency check.

### 2.9. Cascade Integrity Across the Vendor, Pricing, and Sanction Aggregates

This system's hardest correctness requirement is that a single client call frequently mutates several aggregates, and the secondary mutations are as much part of the contract as the primary one. Four cascade families run through the whole specification, and each is stated in full where its workflow lives in §3:

- **Peer group membership.** A peer group's `member_count` is the number of vendors assigned to it whose `authorization_status` is `AUTHORIZED`, `REAUTH_PENDING`, or `SUSPENDED`. Vendors in `APPLICANT`, `IN_REVIEW`, `DENIED`, or `DISQUALIFIED` are not counted, and vendors with no peer group assigned are not counted at all. Every transition into or out of that membership set adjusts the count by one and increments the peer group's `version` by one. Summed across all peer groups, `member_count` always equals the number of vendors with a non-null `peer_group_id` in one of those three statuses — a global invariant that must survive every forward action and every compensating one.
- **Delisting and voiding.** Removing a UPC from the authorized food list supersedes its ceilings, voids the shelf-price submissions that fed them, and re-derives the affected vendors' authorization readiness. Losing a vendor to denial or disqualification voids that vendor's live submissions in the same way.
- **Money reversal.** Applying a reimbursement adjustment moves money on the claim, on each affected claim line, and on the vendor. Reversing it restores all three exactly, so that the claim's `adjudicated_total_cents` always equals its `net_payable_cents` plus the sum of `recoupment_cents` over its adjustments in status `APPLIED`, and a vendor's `recoupment_balance_cents` always equals the sum of `recoupment_cents` over that vendor's adjustments in status `APPLIED`.
- **Finding escalation.** A failed monitoring visit can, within the same request, raise a finding count, flip a risk flag, cause the system to schedule a follow-up visit of its own accord, and place a hold on reauthorization. Each hop is conditional on the previous one having actually changed something.

### 2.10. Segregation of Duties in Money and Sanction Decisions

Two decisions may not be made by the person who set them up. A pending reimbursement adjustment may not be applied by the same principal that created it: if `X-User-ID` equals the adjustment's `created_by_user_id`, the apply is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Likewise, a disqualification may not be imposed by the principal that opened the case: if `X-User-ID` equals the case's `opened_by_user_id`, the imposition is rejected with the same error. Because a case opened by the risk run records the literal string `SYSTEM` as its `opened_by_user_id`, no human operator can ever collide with it, and system-opened cases are always imposable by any authorized supervisor or investigator.

## 3. Business Logic & Workflows

### 3.1. Configuring Peer Groups and the Authorized Food List

Before any vendor can be processed, a `VendorUnitSupervisor` lays down the two reference structures the rest of the system reads: peer groups, which decide how a vendor is compared to its competitors, and the authorized food list, which decides what may be sold.

A **peer group** is created with a `code` — a human-readable label between 1 and 32 characters, unique across all peer groups regardless of their status, compared case-sensitively, so `SUPER-A` and `super-a` are two different codes and both may exist. The group declares the `store_type` it covers, one of `SUPERMARKET`, `SUPERSTORE`, `MEDIUM_GROCERY`, `SMALL_GROCERY`, or `PHARMACY`, and a monthly redemption volume band whose lower bound `min_monthly_redemption_cents` must be at least 0 and whose upper bound `max_monthly_redemption_cents` is either null, meaning the band is unbounded above, or a value at least equal to the lower bound. Both bounds are inclusive when a vendor is matched against them. The group also declares its competitive price criterion `mar_method`, one of `PEER_MEDIAN`, `PEER_PERCENTILE_75`, or `LOWEST_HALF_AVG`; a `competitive_allowance_pct` between 0 and 0.25 inclusive, expressed as a fraction rather than a percentage figure; a `min_submissions_for_ceiling` of at least 1, which defaults to 3 when the field is omitted from the create payload; and a `min_stock_multiplier` between 0.5 and 3.0 inclusive that scales every minimum stock requirement for its members. A new peer group begins with `status` `ACTIVE`, a `member_count` of 0, and a null `retired_at`.

Retiring a peer group is how the agency closes a band without deleting history. Retirement, restricted to a `VendorUnitSupervisor`, sets `status` to `RETIRED` and stamps `retired_at` with the logical clock. A `RETIRED` group never enters the candidate set for a new assignment, and it blocks the authorization of members that were still being processed: every vendor assigned to the retiring group whose `authorization_status` is `IN_REVIEW` or `REAUTH_PENDING` has its `authorization_blocked_reason` stamped with the explanation `PEER_GROUP_RETIRED`. Members already `AUTHORIZED` keep operating and remain counted in `member_count`; retirement does not change the count.

The **authorized food list** has two levels. A `FoodCategory` is created with a `code` unique across all categories and a display `name`, plus the rules that govern everything inside it: `is_formula` marks the category as infant formula; `formula_restriction_level` is `NONE`, `CONTRACT_BRAND_ONLY`, or `MEDICAL_DOC_REQUIRED`; `min_stock_units` (at least 0) is the baseline unit count a store must carry before the peer group multiplier is applied; `min_variety_count` (at least 0) is the number of distinct varieties required; `max_units_per_transaction` (at least 1) is the per-line quantity ceiling enforced during claim adjudication; and `stock_required` decides whether the category participates in minimum stock verification at all.

Under a category, each UPC on the shelf becomes an `AuthorizedFoodItem`, created with the `food_category_id` of its governing category, a `upc` of 8 to 14 digits as printed on the package, a `brand` label, a `container_size_oz` greater than 0, a `contract_brand` flag marking it as the state contract brand for its formula category, and an optional `required_for_authorization` flag that defaults to false. The `upc` must be unique among items whose `status` is `ACTIVE`; a delisted item's UPC may be reused, and duplicate live UPCs are refused with `ERR_DUPLICATE_UPC`. A new item begins `ACTIVE`, with `delisted_at` and `delist_reason` both null.

Delisting a UPC is the most far-reaching configuration action in the system, and it runs as a four-hop cascade driven by a `VendorUnitSupervisor` who supplies a free-text `delist_reason`. In the first hop, the item's `status` becomes `DELISTED` while `delisted_at` takes the logical clock and `delist_reason` is stored. In the second hop, because the item is no longer authorized, every PriceCeiling for that item whose `status` is `PROVISIONAL` or `ACTIVE` moves to `SUPERSEDED` with `superseded_reason` `ITEM_DELISTED`. In the third hop, because no ceiling remains to serve as an adjudication basis, every PriceSubmission for that item whose `status` is `SUBMITTED` or `ACCEPTED`, and whose price cycle is itself `OPEN` or `CLOSED`, moves to `VOIDED` with `voided_reason` `ITEM_DELISTED` — submissions belonging to a `PUBLISHED` cycle are left alone, because that cycle's history is closed. In the fourth hop, because those submissions were voided, each affected vendor's `accepted_submission_count` is decremented and its `price_submission_complete` is recomputed, turning false when the delisted item had `required_for_authorization` set to true.

### 3.2. Vendor Intake, Peer Group Assignment, and Training Currency

A `VendorUnitAnalyst` records an application with the store's `store_name`, its declared `store_type` from the same five-value list the peer groups use, and its self-reported `reported_monthly_redemption_cents`, which must be at least 0. The new Vendor begins in `authorization_status` `APPLICANT` with a null `peer_group_id`, a `risk_score` of 0.0, and a `risk_tier` of `LOW`. Every other computed field starts at its documented baseline: `reauth_completed_count`, `accepted_submission_count`, `open_finding_count`, `recoupment_balance_cents`, `avg_monthly_redemption_cents`, and `sanction_points` at 0; `price_submission_complete` and `compliance_buy_required` and `reauthorization_hold` false; `risk_flag` `NONE`; and `authorized_at`, `reauthorization_due_at`, `training_type`, `training_completed_at`, `training_expires_at`, `cure_deadline_at`, `risk_epoch_at`, `reauth_blocked_reason`, `authorization_blocked_reason`, `disqualified_until`, and `denial_reason` all null.

**Training** is recorded separately from the application and may be recorded at any point in the vendor's life. An analyst records a session by supplying its `training_type` — `INITIAL`, `ANNUAL`, or `CORRECTIVE` — and the instant it finished as `completed_at`, which the server stores as the vendor's `training_completed_at`. From that instant the server derives `training_expires_at` by adding twelve calendar months to `training_completed_at` under the month arithmetic of §2.5. Training is **current** if and only if `training_expires_at` is not null and the logical clock is strictly earlier than it; a clock exactly equal to `training_expires_at` means the training has lapsed. A vendor with no training on file, or with lapsed training, cannot be authorized or reauthorized, and both attempts are refused with `ERR_VENDOR_TRAINING_EXPIRED`. Recording a new session simply overwrites `training_type`, `training_completed_at`, and `training_expires_at`; the system keeps only the most recent session.

Submitting the application moves the vendor from `APPLICANT` to `IN_REVIEW` and is the moment the peer group is chosen. Only a vendor still in `APPLICANT` may be submitted; anything else is refused with `ERR_INVALID_VENDOR_STATE`. A vendor whose disqualification period has not elapsed — that is, whose `disqualified_until` is set and the logical clock has not yet reached it — may not be put back into review, and the attempt is refused with `ERR_VENDOR_DISQUALIFIED`.

**Peer group assignment** proceeds in four steps and is fully deterministic. First, the eligible candidates are collected: every peer group whose `status` is `ACTIVE`, whose `store_type` equals the vendor's `store_type`, whose `min_monthly_redemption_cents` is less than or equal to the vendor's `reported_monthly_redemption_cents`, and whose `max_monthly_redemption_cents` is either null or greater than or equal to the vendor's reported volume. Both band bounds are inclusive, and `RETIRED` groups are never candidates no matter how well they match. Second, each candidate is measured by band width: the upper bound minus the lower bound, where a null upper bound is treated as the sentinel value of one trillion cents — that is, 1,000,000,000,000 cents — so an unbounded band is always the widest and therefore the least specific match. Third, the candidates are ordered by band width ascending, then by `min_monthly_redemption_cents` ascending, then by `created_at` ascending, and the first candidate in that order wins; the vendor's `peer_group_id` is set to that group's identifier. Fourth, if the candidate set is empty, no assignment happens and the submission is refused with `ERR_NO_PEER_GROUP_MATCH` (HTTP 422).

The same request also recomputes `price_submission_complete` against the current price cycle — it stays false while no required item has an accepted submission — and clears `authorization_blocked_reason` back to null, because entering review resets any block inherited from an earlier round.

**Price submission completeness** is the readiness test the authorization decisions depend on, and it has its own governing-cycle rule which is deliberately independent of cycle status. The candidate cycles are every PriceCycle whose `status` is `OPEN`, `CLOSED`, or `PUBLISHED` and whose `submission_open_at` is at or before the logical clock. Among those the governing cycle is the one with the greatest `submission_open_at`, and when two share that instant, the one with the greater `created_at`. The required items are every AuthorizedFoodItem whose `status` is `ACTIVE` and whose `required_for_authorization` is true. Against the governing cycle, `accepted_submission_count` is the number of the vendor's own PriceSubmissions in that cycle whose `status` is `ACCEPTED`, and `price_submission_complete` is true when, for every required item, such an accepted submission exists from this vendor in the governing cycle. Two degenerate cases both resolve to true: when no candidate cycle exists at all, completeness is vacuously satisfied; and when the required item set is empty, the all-of test is likewise satisfied. Submissions in `SUBMITTED`, `REJECTED`, or `VOIDED` never count toward completeness, and an item that has been delisted drops out of the required set entirely.

### 3.3. The Competitive Price Cycle: Shelf-Price Submission and Review

Competitive pricing is organized into cycles. A `VendorUnitSupervisor` opens a cycle with a `cycle_code` unique across all cycles and a **half-open** collection window running from `submission_open_at` inclusive to `submission_due_at` exclusive. The two instants must satisfy the earlier being strictly before the later, or the create is refused with `ERR_INVALID_CYCLE_WINDOW` (HTTP 422). The new window must also not intersect the half-open window of any existing cycle whose `status` is `OPEN`, `CLOSED`, or `PUBLISHED`; because the windows are half-open at their upper end, a new window beginning exactly at an existing window's `submission_due_at` is permitted, while any true overlap is refused with `ERR_CYCLE_WINDOW_OVERLAP`. A new cycle starts `OPEN`, with `closed_at`, `published_at` null and `provisional_ceiling_count`, `published_ceiling_count`, and `skipped_pair_count` at 0.

A `VendorOperator` reports a shelf price by supplying the `vendor_id` it is acting as, the `food_item_id` being priced, the `price_cycle_id` it belongs to, and the `shelf_price_cents` for one container, which must be at least 1. The submission begins in `status` `SUBMITTED` with `revision_count` 0 and with `review_reason`, `reviewed_by_user_id`, `reviewed_at`, and `voided_reason` all null. Two constraints guard the create. The cycle must be `OPEN` and the logical clock must fall inside the half-open window — at or after `submission_open_at` and strictly before `submission_due_at` — or the request is refused with `ERR_SUBMISSION_WINDOW_CLOSED`. And no other submission may already exist for the same combination of vendor, food item, and cycle in `status` `SUBMITTED`, `ACCEPTED`, or `REJECTED`; a previously `VOIDED` submission does not block a fresh one, and a live collision is refused with `ERR_DUPLICATE_PRICE_SUBMISSION`. A vendor still inside a disqualification period cannot submit prices at all, and is refused with `ERR_VENDOR_DISQUALIFIED`.

Review is the analyst's judgement on whether a reported price is plausible. A `VendorUnitAnalyst` reviews a submission that is still `SUBMITTED` — any other status is refused with `ERR_INVALID_SUBMISSION_STATE` — by supplying a `decision`. A decision of `ACCEPT` moves the submission `SUBMITTED → ACCEPTED`. A decision of `REJECT` moves it `SUBMITTED → REJECTED` and requires a `review_reason` in the body, one of `PRICE_IMPLAUSIBLE`, `MISSING_DOCUMENTATION`, or `ABOVE_STATEWIDE_OUTLIER`; a rejection with no reason supplied is refused with `ERR_INVALID_REQUEST`. Both outcomes stamp `reviewed_by_user_id` from the acting `X-User-ID` and `reviewed_at` from the logical clock, and both recompute the submitting vendor's `accepted_submission_count` and `price_submission_complete` — acceptance can complete a vendor's readiness, and rejection can undo it.

A rejected submission can be revised, and this is the one cycle in the pricing workflow. The `VendorOperator` supplies a replacement `shelf_price_cents`, which moves the submission `REJECTED → SUBMITTED` for a fresh review, increments `revision_count` by one, and resets `review_reason`, `reviewed_by_user_id`, and `reviewed_at` to null. Three conditions gate the revision. The submission must actually be `REJECTED`, or the request is refused with `ERR_INVALID_SUBMISSION_STATE`. The revision budget must not be exhausted: a submission may be revised while its `revision_count` is strictly less than two, so the first and second revisions are allowed and a third attempt — arriving when `revision_count` already stands at 2 — is refused with `ERR_REVISION_LIMIT_REACHED`. And the cycle must still be `OPEN` with the logical clock inside the same half-open window that governs a fresh submission, or the revision is refused with `ERR_SUBMISSION_WINDOW_CLOSED`.

### 3.4. Deriving the Maximum Allowable Reimbursement

Closing a cycle and publishing its ceilings are two separate supervisor actions, and they run the **same** derivation over **different** candidate sets. That divergence is intentional: closing produces a preview the vendor unit can inspect, publishing produces the number that will actually pay claims.

Closing moves a cycle `OPEN → CLOSED` — a cycle in any other status is refused with `ERR_INVALID_CYCLE_STATE` — stamps `closed_at` with the logical clock, and sweeps every pair consisting of an `ACTIVE` peer group and an `ACTIVE` authorized food item. For each pair with a non-empty candidate set, a PriceCeiling row is written with `status` `PROVISIONAL`; the number written becomes the cycle's `provisional_ceiling_count`, and the number of pairs skipped for having an empty candidate set becomes its `skipped_pair_count`.

Publishing moves a cycle `CLOSED → PUBLISHED` — again `ERR_INVALID_CYCLE_STATE` for any other status — stamps `published_at`, and performs three passes. First, every PriceCeiling of this cycle still in `PROVISIONAL` moves to `SUPERSEDED` with `superseded_reason` `PROVISIONAL_REPLACED`. Second, the same pair sweep runs again and writes a fresh PriceCeiling row with `status` `ACTIVE` for every pair with a non-empty candidate set, setting `published_ceiling_count` and `skipped_pair_count` from that sweep. Third, for every peer-group-and-item pair published in this pass, any PriceCeiling from an earlier cycle that was still `ACTIVE` for that same pair moves to `SUPERSEDED` with `superseded_reason` `NEWER_CYCLE_PUBLISHED`, so that at most one active ceiling per pair survives. The response to publication reports the `price_cycle_id`, the resulting `status`, the `published_ceiling_count`, the `skipped_pair_count`, a `superseded_ceiling_count` covering every row this call moved to `SUPERSEDED`, and the `published_at` instant.

**The derivation itself**, evaluated once per pair of an `ACTIVE` peer group and an `ACTIVE` item, proceeds as follows.

Begin with the peer candidate list: the `shelf_price_cents` of every PriceSubmission belonging to this cycle and this item, whose `status` is in the set the variant allows, whose submitting vendor is assigned to this peer group, and whose submitting vendor's `authorization_status` at evaluation time is `IN_REVIEW`, `AUTHORIZED`, or `REAUTH_PENDING`. Sort those prices ascending, breaking ties between equal prices by the submission's `created_at` ascending. The count of that list is recorded as `peer_submission_count`.

If the peer list is empty, the pair is skipped entirely: no PriceCeiling row is written for it and the cycle's `skipped_pair_count` rises by one. Otherwise the basis is decided by comparing the peer count against the peer group's own `min_submissions_for_ceiling`. When the peer count is greater than or equal to that threshold, `basis` is `PEER_GROUP` and the candidate set is the peer list itself. When the peer count falls short, `basis` is `STATEWIDE_FALLBACK` and the candidate set is rebuilt with the identical filter but **without** the peer-group restriction, restricted to submissions from vendors whose own peer group has `status` `ACTIVE`; that broader list is likewise sorted ascending by price with the `created_at` tie-break. Either way, the size of the candidate set actually used is recorded as `contributing_submission_count`, while `peer_submission_count` continues to report the peer count even when the fallback was used.

The base price is then read out of the candidate set according to the peer group's `mar_method`. Under `PEER_MEDIAN`, the base is the median: for a candidate set of odd size it is the single middle element, and for an even size it is the mean of the two middle elements. Under `PEER_PERCENTILE_75`, the base is the nearest-rank seventy-fifth percentile: multiply 0.75 by the number of candidates, round that product **up** to the next whole number, and take the element at that one-based position in the ascending list — so with four candidates the third-lowest price is taken, and with five candidates the fourth. Under `LOWEST_HALF_AVG`, take the number of candidates, divide by two, round **up** to a whole number to get how many of the lowest prices participate, and average exactly those lowest prices — so with five candidates the three lowest are averaged. The unrounded result is stored as `base_cents`.

The step order from base price to final ceiling is pinned and must not be rearranged. The allowance is applied first: the base is multiplied by one plus the peer group's `competitive_allowance_pct`, giving an allowance-adjusted figure. The statewide cap is computed second, as 1.25 times the smallest price in the **same** candidate set that produced the base — not the smallest peer price when the fallback was used, and not a statewide minimum computed separately. That unrounded cap is stored as `cap_cents`, and `cap_binding` is recorded as true exactly when the cap is strictly less than the allowance-adjusted figure. Rounding happens once, at the very end: `mar_cents` is the lesser of the allowance-adjusted figure and the cap, rounded half up to a whole cent. Both `base_cents` and `cap_cents` remain unrounded decimals on the row, so that an appeal can retrace the arithmetic. Each row also records the `peer_group_id`, `food_item_id`, and `price_cycle_id` it belongs to, and an `effective_from` instant set to the logical clock at which the row became effective.

The two variants differ only in which submission statuses are allowed into the initial list, and the difference is consequential. The `PROVISIONAL` variant, run at cycle close, admits submissions in `SUBMITTED` as well as `ACCEPTED` — the preview therefore includes prices no analyst has yet vetted. The `FINAL` variant, run at publication, admits only `ACCEPTED` submissions, so a submission that was never reviewed silently drops out, shifting both the base and the cap's minimum. Submissions in `REJECTED` or `VOIDED` enter neither set. On identical data the two variants can and routinely will produce different `mar_cents`, different `basis` values, and different `cap_binding` flags for the same pair.

### 3.5. Authorization, Reauthorization, and Denial Decisions

Authorizing a vendor is a supervisor decision that turns a reviewed application into an operating WIC vendor, advancing `authorization_status` from `IN_REVIEW` to `AUTHORIZED`. Five conditions must hold, and when several fail the ladder of §2.7 decides which rejection the client sees. The vendor must actually be `IN_REVIEW`, or the request is refused with `ERR_INVALID_VENDOR_STATE`. Its training must be current in the strict sense of §3.2, or `ERR_VENDOR_TRAINING_EXPIRED`. No sanction case of the vendor may sit in `OPENED` or `NOTICE_SERVED`, or `ERR_OPEN_SANCTION_CASE_EXISTS`. Its assigned peer group must still be `ACTIVE`, or `ERR_PEER_GROUP_RETIRED`. And `price_submission_complete` must be true, or `ERR_PRICE_SUBMISSIONS_INCOMPLETE`. Ordered as the ladder requires, training currency is checked before the open-case test, the open-case test before the peer group test, and the peer group test before submission completeness — so a vendor with lapsed training and a retired peer group reports the training failure.

On success the vendor gains `authorized_at` from the logical clock and a `reauthorization_due_at` set to thirty-six calendar months after `authorized_at`. The assigned peer group's `member_count` rises by one and its `version` increments by one, because the vendor has just entered the membership set of §2.9. And `avg_monthly_redemption_cents` is recomputed, which matters far downstream: it is the base of every civil money penalty.

**The redemption average** is derived from the vendor's own claim history. Take the vendor's RedemptionClaims whose `status` is `ADJUDICATED`, `ADJUSTED`, or `PAID`; claims still in `SUBMITTED` are excluded and never influence the average. Compare their `claim_month` values as strings in descending order and keep the six greatest distinct months. Gather every qualifying claim whose `claim_month` falls in that set of months. If no such claim exists, `avg_monthly_redemption_cents` falls back to the vendor's self-reported `reported_monthly_redemption_cents`. Otherwise it is the sum of `adjudicated_total_cents` over those claims divided by the **number of distinct months** kept — not the number of claims, so two claims in the same month raise the numerator without raising the divisor — rounded half up to a whole cent.

**Reauthorization** is the cycle that keeps an authorized vendor authorized. An analyst opens it, moving `AUTHORIZED → REAUTH_PENDING`, but only once the window has been reached: the logical clock must be at or after ninety days before `reauthorization_due_at`, and the boundary is inclusive, so a clock landing exactly ninety days before the due date qualifies. An earlier attempt is refused with `ERR_REAUTH_WINDOW_NOT_OPEN`. Opening the cycle recomputes `accepted_submission_count` and `price_submission_complete` against the current cycle, and stamps `reauth_blocked_reason` with the explanation `PENDING_COMPLIANCE_BUY` when `reauthorization_hold` is already true at that moment; otherwise the reason is set to null.

Completing reauthorization is a supervisor decision moving `REAUTH_PENDING → AUTHORIZED`, and it repeats the authorization gauntlet with one addition. The vendor must be `REAUTH_PENDING`; its training must be current, or `ERR_VENDOR_TRAINING_EXPIRED`; no case of the vendor may be `OPENED` or `NOTICE_SERVED`, or `ERR_OPEN_SANCTION_CASE_EXISTS`; `reauthorization_hold` must be false, or `ERR_REAUTHORIZATION_HOLD`; the peer group must be `ACTIVE`, or `ERR_PEER_GROUP_RETIRED`; and `price_submission_complete` must be true against the current cycle, or `ERR_PRICE_SUBMISSIONS_INCOMPLETE`. In the §2.7 ordering the segregation and training checks come first, then the open-case test, then the hold, then the peer group, then completeness — the hold is checked before the peer group and completeness tests, so a held vendor that also lacks submissions reports the hold. On success, `reauthorization_due_at` is advanced by thirty-six calendar months **from its own previous value**, never from the logical clock, so that a vendor completing late does not gain extra time and cycles never drift; `reauth_completed_count` rises by one; and `reauth_blocked_reason` is cleared to null. This closes the cycle `AUTHORIZED → REAUTH_PENDING → AUTHORIZED`.

**Denial** ends the relationship before it begins, or ends it at renewal. A supervisor may deny a vendor whose `authorization_status` is either `IN_REVIEW` or `REAUTH_PENDING`, supplying a `denial_reason` that is stored on the vendor; any other starting status is refused with `ERR_INVALID_VENDOR_STATE`. `DENIED` is terminal. Denial carries the same submission cascade in both cases: every PriceSubmission of the vendor whose `status` is `SUBMITTED` or `ACCEPTED`, and whose price cycle is `OPEN` or `CLOSED`, moves to `VOIDED` with `voided_reason` `VENDOR_DISQUALIFIED`. The two starting states differ in exactly one respect, and it follows from §2.9: a vendor denied out of `REAUTH_PENDING` was a counted member of its peer group, so that group's `member_count` is decremented by one and its `version` increments by one, whereas a vendor denied out of `IN_REVIEW` was never counted and no peer group is touched.

### 3.6. Monitoring Visits, Minimum Stock Verification, and the Compliance-Buy Cascade

Monitoring is how the agency confirms that an authorized store actually stocks WIC foods and charges WIC prices. A visit is scheduled with the `vendor_id` to be monitored, a `visit_type` of `ROUTINE`, `COMPLIANCE_BUY`, or `HIGH_RISK_FOLLOWUP`, and a `scheduled_for` instant. Client-created visits begin `SCHEDULED` with `auto_generated` false, an `outcome` of `PENDING`, an `overcharge_cents` of 0, a `stock_compliance_pct` of 0.0, and `conducted_at` and `cancelled_reason` null.

Four rules gate scheduling. The vendor must be **monitorable** — its `authorization_status` must be `AUTHORIZED`, `REAUTH_PENDING`, or `SUSPENDED`, since a suspended store is still a store that can be inspected — and any other status is refused with `ERR_VENDOR_NOT_MONITORABLE`. A `COMPLIANCE_BUY` may only be created by a `ComplianceInvestigator`, as §2.1 requires, and it may only be created when the vendor actually warrants one: either `compliance_buy_required` is true or `risk_tier` is `HIGH`. A compliance buy scheduled against a vendor that is neither flagged nor in the top risk tier is refused with `ERR_COMPLIANCE_BUY_NOT_WARRANTED`. The `scheduled_for` instant must not be earlier than the logical clock — an instant exactly equal to the clock is acceptable — and a past date is refused with `ERR_VISIT_DATE_IN_PAST` (HTTP 422). Finally, a blackout buffer keeps visits from clustering: if any other visit of the same vendor is still `SCHEDULED` and the gap between its `scheduled_for` and the new one is seven days or less in either direction, the new visit is refused with `ERR_VISIT_BLACKOUT_CONFLICT`. The buffer is a closed symmetric window, so a gap of exactly seven days conflicts and a gap of eight days does not. System-created compliance buys bypass this rule entirely. Creating a `COMPLIANCE_BUY` visit through the API also sets the vendor's `reauthorization_hold` to true, because a pending compliance buy blocks the completion of a reauthorization cycle.

Before a visit is concluded, the field staff record what they saw, one category at a time. Each observation supplies the `food_category_id` observed, the `observed_units` counted on the shelf, and the `observed_variety_count` of distinct varieties. Each observation appends an entry to the visit's `stock_findings`, initially without a `verdict` or a `required_units` figure — those are stamped only when the visit is conducted. At most one observation may exist per visit and category pair; a second observation for the same category is refused with `ERR_DUPLICATE_OBSERVATION`. Observations may only be recorded while the visit is `SCHEDULED`, and otherwise are refused with `ERR_INVALID_VISIT_STATE`.

**Conducting** the visit is the moment the verdict is computed. Only a `SCHEDULED` visit may be conducted — `ERR_INVALID_VISIT_STATE` otherwise — and the vendor must still be monitorable, or `ERR_VENDOR_NOT_MONITORABLE`. The payload optionally carries `buy_items`, the compliance-buy basket, as a list of objects each holding the `upc` purchased, the `quantity` of containers bought, and the `charged_unit_price_cents` the register actually charged; for visit types other than a compliance buy the basket is empty. Conducting stamps `conducted_at` from the logical clock and computes, in this order, the stock verdicts, the overcharge, and the visit `outcome`.

**Minimum stock verification** works over the categories that participate: every FoodCategory whose `stock_required` is true, considered globally and processed in ascending `code` order. The multiplier comes from the peer group of the visited vendor: its `min_stock_multiplier`. For each participating category, the requirement is the category's `min_stock_units` multiplied by that multiplier and rounded **up** to a whole number, and that figure is stamped onto the finding as `required_units`. The category's verdict is then decided by the first of these tests that applies: if no observation was recorded for the category at all, the verdict is `MISSING` and the server creates the finding entry itself with `observed_units` 0 and `observed_variety_count` 0; otherwise, if `observed_units` is strictly less than `required_units`, the verdict is `BELOW_UNITS`; otherwise, if `observed_variety_count` is strictly less than the category's `min_variety_count`, the verdict is `BELOW_VARIETY`; otherwise the verdict is `PASS` and the category counts as passing. The `stock_compliance_pct` is then 100 multiplied by the number of passing categories divided by the number of participating categories, rounded half up to one decimal place; when no category participates at all, the figure is exactly 100.0.

The `outcome` is decided by a strict precedence over those results. If any participating category came out `MISSING`, the outcome is `FAIL_MISSING_CATEGORY`. Otherwise, if fewer categories passed than participated — meaning at least one `BELOW_UNITS` or `BELOW_VARIETY` verdict — the outcome is `FAIL_BELOW_MINIMUM`. Otherwise, if the visit's `overcharge_cents` is greater than 0, the outcome is `FAIL_PRICE_OVERCHARGE`. Otherwise the outcome is `PASS`. A missing category therefore always outranks an overcharge in the reported outcome, even though both are failures.

**The compliance-buy overcharge** is computed from `buy_items` whenever the basket is non-empty. First the governing cycle is chosen: among price cycles whose `status` is `PUBLISHED` and whose `published_at` is at or before the logical clock, the one with the greatest `published_at`, ties broken by the earlier `created_at`; if no such cycle exists, `overcharge_cents` is 0 and the basket is not priced. Otherwise the basket entries are walked in payload order. For each entry the item is resolved from its `upc`, and the ceiling is the PriceCeiling for that item, the visited vendor's peer group, and the governing cycle whose `status` is `ACTIVE`. If either the item or the ceiling cannot be found, the entry contributes nothing and the walk continues — unpriced items are not treated as overcharges. Otherwise the entry contributes the excess of `charged_unit_price_cents` over the ceiling's `mar_cents`, floored at zero so a bargain never offsets an overcharge, multiplied by the entry's `quantity`. The contributions are added into `overcharge_cents`.

A visit whose outcome is `PASS` moves `SCHEDULED → PASSED`, stamping `conducted_at`, the outcome, the `stock_findings` verdicts, and `stock_compliance_pct`. A passing `HIGH_RISK_FOLLOWUP` visit does considerably more, and it is the vendor's route back from trouble. In order: every other MonitoringVisit of the same vendor still in `FAILED` moves to `CURED`, which requires that the vendor's `cure_deadline_at` is not null and the logical clock is at or before it; then the vendor's `open_finding_count` is reset to 0 and its `cure_deadline_at` to null; then `compliance_buy_required` is set to false and `risk_flag` back to `NONE`; then any still-`SCHEDULED` `COMPLIANCE_BUY` visit is deliberately left in place, and `reauthorization_hold` is recomputed from whether such a visit still exists — so a vendor cured while a compliance buy remains booked stays held. Independently of the visit type, if the vendor was `SUSPENDED` and no sanction case of that vendor remains in `OPENED` or `NOTICE_SERVED`, the pass returns the vendor's `authorization_status` from `SUSPENDED` to `AUTHORIZED` and resets `risk_flag` to `NONE`.

A visit whose outcome is any of the three failure values moves `SCHEDULED → FAILED` and triggers a four-hop cascade, where each hop fires only because the previous one changed something.

- **Hop 1** always runs: `conducted_at`, the `outcome`, the `stock_findings` verdicts, `stock_compliance_pct`, and `overcharge_cents` are stamped; the vendor's `open_finding_count` rises by one; and the vendor's `cure_deadline_at` is set to thirty days after the logical clock, opening the cure window.
- **Hop 2** fires only when `open_finding_count` has thereby reached two uncured findings: the vendor's `compliance_buy_required` flips to true and its `risk_flag` becomes `HIGH_FINDING_COUNT`.
- **Hop 3** fires only because hop 2 flipped `compliance_buy_required` to true: the system creates a MonitoringVisit of its own for the same vendor with `visit_type` `COMPLIANCE_BUY`, `status` `SCHEDULED`, `auto_generated` true, and `scheduled_for` set to fourteen days after the logical clock. Being system-created, this visit is exempt from the seven-day blackout rule and may land inside another visit's buffer.
- **Hop 4** fires only because a `SCHEDULED` `COMPLIANCE_BUY` visit now exists: the vendor's `reauthorization_hold` flips to true, and if the vendor happens to be `REAUTH_PENDING` at that moment, its `reauth_blocked_reason` is stamped `PENDING_COMPLIANCE_BUY`.

The first failing visit of an otherwise clean vendor therefore stops after hop 1: one finding is recorded, a cure deadline is set, and nothing else moves. It is the second uncured failure that manufactures the compliance buy and the reauthorization hold.

A failed visit has two exits. Curing it, described above, is the vendor's own remedy and requires the pass to arrive at or before `cure_deadline_at`. Escalation is the agency's remedy when the cure window lapses, and it is driven by the risk run described in §3.9.

### 3.7. Redemption Claims and Transaction Edits

A `VendorOperator` files a month of redemptions by supplying its `vendor_id`, the benefit month as `claim_month` in four-digit-year-hyphen-two-digit-month form, and a non-empty list of `lines`. Each entry becomes a ClaimLine carrying its `line_number` — a one-based position that must be at least 1 and must not repeat within the claim — the `upc` as scanned at the register, the `quantity` of containers redeemed, the `charged_unit_price_cents` per container which must be at least 0, and an optional `medical_doc_on_file` flag defaulting to false that records whether medical documentation backs an exempt-formula line. Each line records the `redemption_claim_id` of the claim it belongs to.

At creation the claim's `status` is `SUBMITTED`, its `line_count` is the number of lines created, and its `submitted_total_cents` is the sum over lines of `quantity` multiplied by `charged_unit_price_cents`. Every line starts with `edit_result` `PENDING` and with `edit_code`, `food_item_id`, and `applied_mar_cents` null, `allowed_cents` 0, and `recouped_cents` 0. The claim's `governing_price_cycle_id`, `adjudicated_total_cents`, `net_payable_cents`, `adjudicated_at`, and `paid_at` are all null until adjudication, and `accepted_line_count`, `reduced_line_count`, and `rejected_line_count` all start at 0. Claims may only be filed for a monitorable vendor, or the request is refused with `ERR_VENDOR_NOT_MONITORABLE`, and a vendor inside a live disqualification period cannot file at all, being refused with `ERR_VENDOR_DISQUALIFIED`.

**Adjudication** is where the transaction edits run. A `VendorUnitAnalyst` adjudicates a claim that is still `SUBMITTED`, moving it `SUBMITTED → ADJUDICATED`; any other status is refused with `ERR_INVALID_CLAIM_STATE`. Adjudication requires a published price cycle to exist at or before the logical clock, and without one the request is refused with `ERR_NO_PUBLISHED_PRICE_CYCLE`. The governing cycle is chosen exactly as the compliance-buy pricing chooses it: among cycles whose `status` is `PUBLISHED` and whose `published_at` is at or before the logical clock, the one with the greatest `published_at`, and where two share that instant, the one with the earlier `created_at`. Its identifier is stored on the claim as `governing_price_cycle_id`, and `adjudicated_at` takes the logical clock.

Lines are then processed in ascending `line_number`. For each line the item is resolved by matching the line's `upc` against the authorized food list, using the item's **current** `status` rather than whatever it was during `claim_month`; the resolved identifier is stored as the line's `food_item_id`, and stays null when the UPC does not resolve. The governing ceiling for the line is the PriceCeiling whose peer group is the claiming vendor's `peer_group_id`, whose item is the resolved item, whose cycle is the governing cycle, and whose `status` is `ACTIVE`.

Five edits are then evaluated in a pinned order, and the **first** one that fails decides the line's `edit_code`:

- **`E01`** — the UPC did not resolve to any authorized food item, or the resolved item's `status` is `DELISTED`. The line's `edit_result` becomes `REJECTED` and its `allowed_cents` is 0.
- **`E02`** — a formula restriction is violated. This applies only when the resolved item's category has `is_formula` true, and it fires in either of two ways: the category's `formula_restriction_level` is `CONTRACT_BRAND_ONLY` and the item's `contract_brand` is false, or the level is `MEDICAL_DOC_REQUIRED` and the line's `medical_doc_on_file` is false. A level of `NONE`, or a non-formula category, never triggers this edit. The line becomes `REJECTED` with `allowed_cents` 0.
- **`E03`** — the quantity is out of range: `quantity` is zero or negative, or it exceeds the category's `max_units_per_transaction`. A quantity exactly equal to the ceiling passes. The line becomes `REJECTED` with `allowed_cents` 0.
- **`E04`** — no `ACTIVE` ceiling exists for this peer group, item, and governing cycle, so there is no reimbursement basis. The line becomes `REJECTED` with `allowed_cents` 0.
- **`E05`** — a ceiling exists and was consulted, so the ceiling's `mar_cents` is recorded on the line as `applied_mar_cents`. If the line's `charged_unit_price_cents` is strictly greater than that ceiling, the line's `edit_result` becomes `ACCEPTED_REDUCED` with `edit_code` `E05`, and its `allowed_cents` is the ceiling's `mar_cents` multiplied by `quantity` — the vendor is paid at the ceiling, not at what it charged. If the charged price equals or falls below the ceiling, the line's `edit_result` is `ACCEPTED`, its `edit_code` stays null, and its `allowed_cents` is `charged_unit_price_cents` multiplied by `quantity`. The boundary matters: a charge exactly equal to the ceiling is accepted at full price, not reduced.

Note that `applied_mar_cents` is set only when a ceiling was actually consulted; a line rejected by `E01`, `E02`, `E03`, or `E04` leaves it null.

Once every line is edited, the claim's aggregates are computed. `adjudicated_total_cents` is the sum of `allowed_cents` over all lines. `net_payable_cents` is that total less the sum of `recoupment_cents` over the claim's reimbursement adjustments whose `status` is `APPLIED` — normally zero at first adjudication. `accepted_line_count`, `reduced_line_count`, and `rejected_line_count` count the lines whose `edit_result` is `ACCEPTED`, `ACCEPTED_REDUCED`, and `REJECTED` respectively, over every line regardless of outcome. Note that `submitted_total_cents` was fixed at claim creation and is not recomputed here. Adjudication also refreshes the vendor's `avg_monthly_redemption_cents` per §3.5, since a newly adjudicated month may enter the six-month window.

Marking a claim paid is a supervisor action available from either `ADJUDICATED` or `ADJUSTED`, moving the claim to `PAID` and stamping `paid_at`; any other status is refused with `ERR_INVALID_CLAIM_STATE`. `PAID` is terminal, and from that point any attempt to raise, apply, or reverse an adjustment on the claim is refused with `ERR_CLAIM_ALREADY_PAID`.

### 3.8. Reimbursement Adjustments, Recoupment, and Payment

When an audit, an overcharge finding, or an edit error means the agency paid or is about to pay too much, the correction is a **reimbursement adjustment**. Either a `VendorUnitAnalyst` or a `VendorUnitSupervisor` raises one, supplying the `redemption_claim_id` being adjusted, a `reason_code` of `OVERCHARGE`, `EDIT_ERROR`, `COMPLIANCE_BUY_FINDING`, or `CMP_OFFSET`, a `recoupment_rate` greater than 0 and at most 1, and the `expected_claim_version` required by §2.8. The adjustment begins in `status` `PENDING` with `created_by_user_id` stamped from the acting `X-User-ID` and with `applied_by_user_id`, `applied_at`, `reversed_at`, and `reversal_reason` all null. The claim referenced must already have left `SUBMITTED` — adjudication must have run before any adjustment can exist — and an adjustment raised against a still-submitted claim is refused with `ERR_CLAIM_NOT_ADJUDICATED`. A successful create increments the claim's `version` by one.

**Proration** is computed at create time, not at apply time. The participating lines are the claim's ClaimLines whose `edit_result` is `ACCEPTED` or `ACCEPTED_REDUCED`; lines rejected by any edit are excluded and contribute nothing. Those lines are ordered by ascending `line_number`, and for each one the server records an entry in `line_recoupments` holding the `claim_line_id`, that line's `allowed_cents`, and a `recoupment_cents` equal to the line's `allowed_cents` multiplied by the `recoupment_rate`, rounded half up to a whole cent. The adjustment's own `recoupment_cents` is the sum of those per-line figures. The rounding order is pinned as §2.6 states: each line is rounded first and the rounded shares are summed, so the total may differ by a cent or two from rounding the claim total once, and that residual is deliberately not redistributed. The resulting `recoupment_cents` must not exceed the claim's `net_payable_cents`, treated as zero when the claim has not been adjudicated, and an over-large recoupment is refused with `ERR_RECOUPMENT_EXCEEDS_PAYABLE` (HTTP 422).

**Applying** the adjustment is a supervisor action and moves it `PENDING → APPLIED`. The adjustment must be `PENDING`, or the request is refused with `ERR_INVALID_ADJUSTMENT_STATE`; the acting `X-User-ID` must differ from `created_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES`; the claim must be `ADJUDICATED`, or `ERR_INVALID_CLAIM_STATE`; and the recoupment must still fit inside the claim's current `net_payable_cents`, or `ERR_RECOUPMENT_EXCEEDS_PAYABLE`. On success, `applied_by_user_id` and `applied_at` are stamped, and money moves in three places at once: the claim advances `ADJUDICATED → ADJUSTED` with its `net_payable_cents` reduced by the adjustment's `recoupment_cents`, each participating claim line has its `recouped_cents` increased by that line's prorated share, and the vendor's `recoupment_balance_cents` rises by the adjustment's `recoupment_cents`.

**Reversing** an applied adjustment is the compensating action, also restricted to a supervisor, and moves the adjustment `APPLIED → REVERSED` with a `reversal_reason` stored and `reversed_at` stamped. The adjustment must be `APPLIED`, or `ERR_INVALID_ADJUSTMENT_STATE`, and the claim must be `ADJUSTED`, or `ERR_INVALID_CLAIM_STATE`. Reversal undoes each of the three money effects exactly: each participating line's `recouped_cents` is reduced by the same share it received, returning to 0 when no other adjustment charged it; the vendor's `recoupment_balance_cents` is reduced by the adjustment's `recoupment_cents`; and the claim's `net_payable_cents` is restored. When no other adjustment of the claim remains in `APPLIED`, the claim moves back `ADJUSTED → ADJUDICATED` and its `net_payable_cents` returns to exactly its `adjudicated_total_cents`; when another applied adjustment survives, the claim stays `ADJUSTED` and its `net_payable_cents` reflects the remaining applied recoupments. `REVERSED` is terminal for the adjustment. The two invariants of §2.9 must hold after every apply-and-reverse pair.

### 3.9. High-Risk Identification and the Sanction Schedule

The vendor unit does not investigate at random; it investigates by score. A **risk score** blends the vendor's edit history, its overcharge history, its visit history, and its accumulated sanction points into a single number between 0 and 100.

The score is evaluated over a window ending at a variant-supplied instant and beginning 180 days earlier. Within that window, the claim lines considered are those belonging to the vendor's RedemptionClaims whose `status` is `ADJUDICATED`, `ADJUSTED`, or `PAID` and whose claim's `adjudicated_at` falls after the window start and at or before the window end. From those lines, `edit_rejection_rate_pct` is 100 multiplied by the number of lines whose `edit_result` is `REJECTED` divided by the total number of lines considered, and `price_excess_pct` is 100 multiplied by the number of lines whose `edit_code` is `E05` divided by that same total; when no lines fall in the window, both figures are 0. The visits considered are the vendor's MonitoringVisits whose `status` is `PASSED`, `FAILED`, `CURED`, or `ESCALATED` and whose `conducted_at` falls in the same window, and `failed_visit_pct` is 100 multiplied by the number of those whose `status` is `FAILED` or `ESCALATED` divided by the number considered; with no visits in the window the figure is 0.

The weighted sum takes 0.40 of `edit_rejection_rate_pct`, plus 0.25 of `price_excess_pct`, plus 0.20 of `failed_visit_pct`, plus 15.0 for each of the vendor's `sanction_points` counted up to a cap of two points — so a vendor with three or more points contributes exactly 30.0 from that term, and a vendor with one point contributes 15.0. That sum is rounded half up to one decimal place, and the score is the lesser of 100.0 and that rounded value. The `risk_tier` is then read off the rounded score: `HIGH` when the score is at least 60.0, `ELEVATED` when it is at least 30.0 but below 60.0, and `LOW` below 30.0. Both boundaries are inclusive at the bottom, so a score of exactly 60.0 is `HIGH` and exactly 30.0 is `ELEVATED`.

The score exists in two variants that must not be confused. The **rolling** variant is a computed read available to analysts, supervisors, and investigators; a `basis` query parameter of `ROLLING`, or an omitted `basis`, evaluates the window against the logical clock at request time, so a claim adjudicated one second ago is already counted, and nothing is persisted. The response reports the `vendor_id`, the `basis` used, the `window_start` and `window_end` instants, the `evaluated_line_count` and `evaluated_visit_count` that fell in the window, the three component percentages `edit_rejection_rate_pct`, `price_excess_pct`, and `failed_visit_pct`, the vendor's `sanction_points`, and the resulting `risk_score` and `risk_tier`. The **epoch** variant is the persisted snapshot: a `basis` of `EPOCH` replays whatever the last risk run computed, evaluating the window against the vendor's `risk_epoch_at`. Records created after that run are invisible to the vendor's stored `risk_score` and `risk_tier` until the next run, so the persisted tier — the one that gates compliance-buy eligibility — can lag the rolling tier by a whole epoch.

Advancing the epoch is a `SystemOperator` capability. It walks every non-terminal vendor in ascending `created_at` order, refreshing each vendor's `risk_score`, `risk_tier`, and `risk_epoch_at` from the epoch variant. A vendor whose refreshed `risk_tier` comes out `HIGH` has its `risk_flag` set to `HIGH_SCORE` and its `compliance_buy_required` set to true — the second, score-driven route to a compliance buy alongside the finding-count route of §3.6. Within each vendor, the visits still in `FAILED` are then processed in ascending `scheduled_for` order with `created_at` as the tie-break, and any visit whose vendor's `cure_deadline_at` is not null and is now strictly behind the logical clock moves `FAILED → ESCALATED`. Each escalation opens a SanctionCase for the vendor with `violation_code` `CLASS_C`, `source_visit_id` pointing at the escalated visit, and `opened_by_user_id` set to the literal string `SYSTEM`; because a case is now open, an `AUTHORIZED` vendor moves `AUTHORIZED → SUSPENDED`. The run reports the `epoch_at` instant it used, the `evaluated_vendor_count`, the `high_risk_vendor_count`, the `escalated_visit_count`, and the `opened_sanction_case_count`.

**Opening a sanction case** by hand is a `ComplianceInvestigator` action. It supplies the `vendor_id`, a `violation_code` of `CLASS_A`, `CLASS_B`, `CLASS_C`, or `CLASS_D`, an optional `source_visit_id` naming the monitoring visit that produced the finding (null for cases opened without a visit), a `narrative` supporting the case, and the `expected_vendor_version` required by §2.8. A vendor that already has a case in `OPENED` or `NOTICE_SERVED` cannot have a second one opened, and the attempt is refused with `ERR_OPEN_SANCTION_CASE_EXISTS`. The new case begins in `status` `OPENED` with `resolution` `NONE`, `cmp_paid_cents` 0, and `notice_served_at`, `response_due_at`, and `dismissal_reason` null. `opened_by_user_id` is stamped from the acting `X-User-ID`.

**The sanction schedule** is evaluated once, at open time, in a pinned order that deliberately breaks the apparent circularity between tier, points, and total points. There is exactly one pass:

1. The `base_tier` comes from the violation class: `CLASS_A` is tier 4, `CLASS_B` is tier 3, `CLASS_C` is tier 2, and `CLASS_D` is tier 1.
2. The `case_points` come from the **base** tier and never from the effective one: tier 1 carries 1 point, tier 2 carries 2, tier 3 carries 4, and tier 4 carries 8.
3. The `cumulative_points_at_open` snapshot is the sum of those same base-tier point values over the vendor's **other** sanction cases whose `status` is `CMP_ELECTED`, `DISQUALIFICATION_IMPOSED`, or `CLOSED`. Cases still in `OPENED` or `NOTICE_SERVED`, and cases that ended `DISMISSED`, contribute zero.
4. The escalation step is the number of escalation thresholds — there are two, at 4 points and at 8 points — that the snapshot plus this case's own `case_points` reaches or exceeds. The comparison is inclusive, so a combined total of exactly 4 clears the first threshold and a total of exactly 8 clears both.
5. The `effective_tier` is the base tier plus that escalation step, capped at 4.
6. There is no second iteration: `case_points` is never recomputed from the effective tier.

From the effective tier the remaining figures follow. `disqualification_months` is 0 at tier 1, 6 at tier 2, 12 at tier 3, and 36 at tier 4 — a tier-1 case therefore carries no disqualification at all. `cmp_permitted` is true for every violation class except `CLASS_A`, which may never be settled by money. The `cmp_amount_cents` is the vendor's `avg_monthly_redemption_cents` multiplied by the tier's monthly multiplier — 0.05 at tier 1, 0.10 at tier 2, 0.25 at tier 3, and 0.50 at tier 4 — multiplied again by the tier's month count — 1 month at tier 1, 3 at tier 2, 6 at tier 3, and 12 at tier 4 — then rounded half up to a whole cent, and finally capped: the penalty is the lesser of that rounded figure and 5,625,000 cents, which is the statutory ceiling of fifty-six thousand two hundred fifty dollars. The rounding happens once, before the cap comparison.

**Serving the notice** starts the vendor's clock and may be done by a `ComplianceInvestigator` or a `VendorUnitSupervisor`. The case must be `OPENED`, or the request is refused with `ERR_INVALID_SANCTION_STATE`. The transition `OPENED → NOTICE_SERVED` stamps `notice_served_at` from the logical clock and sets `response_due_at` to fifteen days later — that is the election deadline. If the case's `base_tier` is exactly 4, serving the notice also moves an `AUTHORIZED` vendor `AUTHORIZED → SUSPENDED`; the suspension is a precaution, not a penalty, and because a suspended vendor remains a peer group member, `member_count` is unchanged. Note that this suspension keys off `base_tier`, not `effective_tier`: a tier-3 violation escalated to effective tier 4 does not suspend on notice.

From `NOTICE_SERVED` the case forks, and the two branches have deliberately different consequences.

**Branch A — the civil money penalty.** The `VendorOperator` itself elects to pay, moving the case `NOTICE_SERVED → CMP_ELECTED` and setting `resolution` to `CMP`. The case must be `NOTICE_SERVED`, or `ERR_INVALID_SANCTION_STATE`; `cmp_permitted` must be true, or the election is refused with `ERR_CMP_NOT_PERMITTED`; and the logical clock must be at or before `response_due_at`, with a clock exactly equal to the deadline still qualifying, or the election is refused with `ERR_CMP_ELECTION_WINDOW_EXPIRED`. Electing the penalty leaves the vendor's `authorization_status` untouched and its peer group `member_count` unchanged: the store keeps operating and owes `cmp_amount_cents`. No sanction points are added at election.

**Branch B — disqualification.** A `VendorUnitSupervisor` or a `ComplianceInvestigator` imposes disqualification, moving the case `NOTICE_SERVED → DISQUALIFICATION_IMPOSED` and setting `resolution` to `DISQUALIFICATION`. The case must be `NOTICE_SERVED`, or `ERR_INVALID_SANCTION_STATE`. The acting `X-User-ID` must differ from `opened_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES`. The election window must have closed — the logical clock strictly past `response_due_at` — unless the `violation_code` is `CLASS_A`, for which no election was ever available and imposition is immediate; a premature imposition on a non-`CLASS_A` case is refused with `ERR_ELECTION_WINDOW_OPEN`. And `disqualification_months` must be greater than zero, or the imposition is refused with `ERR_DISQUALIFICATION_NOT_AVAILABLE`, which is what a tier-1 case always yields. The vendor's own status may be `AUTHORIZED`, `REAUTH_PENDING`, or `SUSPENDED` at the time, and from any of those three it moves to `DISQUALIFIED` with the identical cascade:

- `disqualified_until` is set to the logical clock plus `disqualification_months` calendar months.
- `sanction_points` rises by the case's `case_points`.
- The vendor's peer group has its `member_count` decremented by one and its `version` incremented by one.
- Every MonitoringVisit of the vendor still in `SCHEDULED` moves to `CANCELLED` with `cancelled_reason` `VENDOR_DISQUALIFIED`.
- Because those visits are now cancelled, `compliance_buy_required` is set to false and `reauthorization_hold` is recomputed to false.
- Every PriceSubmission of the vendor whose `status` is `SUBMITTED` or `ACCEPTED`, and whose price cycle is `OPEN` or `CLOSED`, moves to `VOIDED` with `voided_reason` `VENDOR_DISQUALIFIED`.

`DISQUALIFIED` is terminal for the vendor. Comparing the two branches: branch A leaves the vendor operating, its peer group membership intact, its visits booked, and its submissions live, and adds no points until the case closes; branch B disqualifies the vendor, decrements the peer group, cancels the visits, voids the submissions, and adds the points immediately.

**Dismissal** is the third exit from `NOTICE_SERVED`, available to a `ComplianceInvestigator` or a `VendorUnitSupervisor` who supplies a `dismissal_reason`. The case must be `NOTICE_SERVED`, or `ERR_INVALID_SANCTION_STATE`. The case moves to `DISMISSED` with `resolution` `DISMISSED`, the reason stored, and no sanction points added at all. If the vendor was `SUSPENDED` and no other case of the vendor remains in `OPENED` or `NOTICE_SERVED`, dismissal returns the vendor `SUSPENDED → AUTHORIZED` and resets its `risk_flag` to `NONE`. Both `DISMISSED` and `CLOSED` are terminal for a case.

**Closure** is the join point where both fork branches converge, and it is a supervisor action. The case must be in `CMP_ELECTED` or `DISQUALIFICATION_IMPOSED`, or the request is refused with `ERR_INVALID_SANCTION_STATE`. Closing from `CMP_ELECTED` carries a `cmp_payment_cents` in the body, and the case may only close when `cmp_paid_cents` plus that payment reaches or exceeds `cmp_amount_cents`; a short payment is refused with `ERR_CMP_UNDERPAID`, while an exact or over-payment closes the case. On success `cmp_paid_cents` is increased by `cmp_payment_cents` and the vendor's `sanction_points` rises by the case's `case_points` — the penalty branch adds its points only at closure. Closing from `DISQUALIFICATION_IMPOSED` needs no payment and moves no money; the vendor's `sanction_points` were already incremented when the disqualification was imposed and are emphatically not incremented a second time. Either way the case's `status` becomes `CLOSED`.

## 4. Endpoint Definitions

Operations that create a new resource — a peer group, a food category, an authorized food item, a vendor application, a price cycle, a price submission, a redemption claim, a reimbursement adjustment, or a sanction case — return `201 Created`. Every other operation, including all state transitions, all cascading actions, all reads, and the two operational capabilities, returns `200 OK`. All paths below are absolute; the API is mounted at the server root with no additional prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/peer-groups` | Create a vendor peer group with its store type, volume band, competitive price criterion and minimum stock multiplier | VendorUnitSupervisor |
| GET | `/peer-groups/{id}` | Read one peer group including its denormalized member count | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator |
| GET | `/peer-groups` | List peer groups with filtering and pagination | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator |
| POST | `/peer-groups/{id}/retire` | Retire a peer group so it stops taking assignments and blocks authorization of its members under review | VendorUnitSupervisor |
| POST | `/food-categories` | Create an authorized food list category with its minimum stock rule, formula restriction and per-transaction quantity ceiling | VendorUnitSupervisor |
| GET | `/food-categories/{id}` | Read one food category | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator, VendorOperator |
| POST | `/authorized-food-items` | Map a UPC into the authorized food list under a category | VendorUnitSupervisor |
| GET | `/authorized-food-items/{id}` | Read one authorized food list item | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator, VendorOperator |
| GET | `/authorized-food-items` | List authorized food list items, filterable by category, UPC and status | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator, VendorOperator |
| POST | `/authorized-food-items/{id}/delist` | Delist a UPC from the authorized food list, cascading through ceilings, submissions and vendor authorization readiness | VendorUnitSupervisor |
| POST | `/vendors` | Record a WIC vendor application | VendorUnitAnalyst |
| GET | `/vendors/{id}` | Read one vendor with its computed authorization, training, risk and money fields | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator, VendorOperator |
| GET | `/vendors` | List vendors, filterable by peer group, authorization status and risk tier | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator |
| GET | `/vendors/{id}/risk-profile` | Computed read of the vendor risk score; the rolling basis evaluates live against the logical clock, the epoch basis replays the last risk run snapshot | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator |
| POST | `/vendors/{id}/record-training` | Record completion of a vendor training session and recompute its expiry | VendorUnitAnalyst |
| POST | `/vendors/{id}/submit-application` | Move an application into review and assign its peer group by store type and volume | VendorUnitAnalyst |
| POST | `/vendors/{id}/authorize` | Authorize a vendor under review once training, price submissions, peer group and sanction status all clear | VendorUnitSupervisor |
| POST | `/vendors/{id}/deny` | Deny a vendor under review or under reauthorization | VendorUnitSupervisor |
| POST | `/vendors/{id}/start-reauthorization` | Open the reauthorization cycle for an authorized vendor once the reauthorization window is reached | VendorUnitAnalyst |
| POST | `/vendors/{id}/complete-reauthorization` | Complete the reauthorization cycle, advancing the due date from its previous value | VendorUnitSupervisor |
| POST | `/price-cycles` | Open a competitive price submission cycle over a half-open window | VendorUnitSupervisor |
| GET | `/price-cycles/{id}` | Read one price cycle with its ceiling counters | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator, VendorOperator |
| POST | `/price-cycles/{id}/close` | Close the submission window and write provisional ceilings from the provisional candidate set | VendorUnitSupervisor |
| POST | `/price-cycles/{id}/publish-ceilings` | Publish the maximum allowable reimbursement per item per peer group from the final candidate set | VendorUnitSupervisor |
| POST | `/price-submissions` | Submit a shelf price for an authorized food list item inside the open cycle window | VendorOperator |
| GET | `/price-submissions/{id}` | Read one shelf price submission | VendorUnitAnalyst, VendorUnitSupervisor, VendorOperator |
| GET | `/price-submissions` | List shelf price submissions, filterable by vendor, item, cycle and status | VendorUnitAnalyst, VendorUnitSupervisor, VendorOperator |
| POST | `/price-submissions/{id}/review` | Accept or reject a shelf price submission against the competitive price criteria | VendorUnitAnalyst |
| POST | `/price-submissions/{id}/revise` | Revise a rejected shelf price submission and put it back into review | VendorOperator |
| GET | `/price-ceilings/{id}` | Read one maximum allowable reimbursement row with its basis, base, cap and contributing counts | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator, VendorOperator |
| GET | `/price-ceilings` | List maximum allowable reimbursement rows, filterable by peer group, item, cycle and status | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator, VendorOperator |
| POST | `/monitoring-visits` | Schedule a routine, compliance-buy or high-risk follow-up monitoring visit | VendorUnitAnalyst, ComplianceInvestigator |
| GET | `/monitoring-visits/{id}` | Read one monitoring visit with its stock findings and overcharge | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator |
| GET | `/monitoring-visits` | List monitoring visits, filterable by vendor, status and visit type | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator |
| POST | `/monitoring-visits/{id}/observations` | Record one minimum stock observation for a food category on a scheduled visit | VendorUnitAnalyst, ComplianceInvestigator |
| POST | `/monitoring-visits/{id}/conduct` | Conduct the visit: verify minimum stock, price the compliance-buy basket, and branch to passed or failed with the corresponding cascade | VendorUnitAnalyst, ComplianceInvestigator |
| POST | `/redemption-claims` | Submit a month of WIC redemption transactions with their scanned lines | VendorOperator |
| GET | `/redemption-claims/{id}` | Read one redemption claim with its adjudication totals | VendorUnitAnalyst, VendorUnitSupervisor, VendorOperator |
| GET | `/redemption-claims` | List redemption claims, filterable by vendor, status, claim month and governing cycle | VendorUnitAnalyst, VendorUnitSupervisor, VendorOperator |
| POST | `/redemption-claims/{id}/adjudicate` | Run the transaction edits against the authorized food list and the published ceilings, rejecting or reducing lines | VendorUnitAnalyst |
| POST | `/redemption-claims/{id}/mark-paid` | Mark an adjudicated or adjusted claim as paid, locking it against further adjustments | VendorUnitSupervisor |
| GET | `/claim-lines/{id}` | Read one claim line with its edit result and reimbursable amount | VendorUnitAnalyst, VendorUnitSupervisor, VendorOperator |
| GET | `/claim-lines` | List claim lines, filterable by claim, resolved item and edit code | VendorUnitAnalyst, VendorUnitSupervisor, VendorOperator |
| POST | `/reimbursement-adjustments` | Raise a reimbursement adjustment against an adjudicated claim; the claim's observed version must still be current | VendorUnitAnalyst, VendorUnitSupervisor |
| GET | `/reimbursement-adjustments/{id}` | Read one reimbursement adjustment with its per-line proration | VendorUnitAnalyst, VendorUnitSupervisor |
| GET | `/reimbursement-adjustments` | List reimbursement adjustments, filterable by claim and status | VendorUnitAnalyst, VendorUnitSupervisor |
| POST | `/reimbursement-adjustments/{id}/apply` | Apply a pending adjustment, recouping from the claim; the applier may not be its creator | VendorUnitSupervisor |
| POST | `/reimbursement-adjustments/{id}/reverse` | Reverse an applied adjustment, restoring the claim and vendor money fields exactly | VendorUnitSupervisor |
| POST | `/sanction-cases` | Open a sanction case under the schedule; the vendor's observed version must still be current | ComplianceInvestigator |
| GET | `/sanction-cases/{id}` | Read one sanction case with its tier escalation and civil money penalty | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator, VendorOperator |
| GET | `/sanction-cases` | List sanction cases, filterable by vendor, source visit and status | VendorUnitAnalyst, VendorUnitSupervisor, ComplianceInvestigator, VendorOperator |
| POST | `/sanction-cases/{id}/serve-notice` | Serve the sanction notice, starting the vendor's election window | ComplianceInvestigator, VendorUnitSupervisor |
| POST | `/sanction-cases/{id}/elect-cmp` | Vendor elects the civil money penalty in lieu of disqualification (fork branch A) | VendorOperator |
| POST | `/sanction-cases/{id}/impose-disqualification` | Impose disqualification once the election window has closed (fork branch B); the imposer may not be the case opener | VendorUnitSupervisor, ComplianceInvestigator |
| POST | `/sanction-cases/{id}/dismiss` | Dismiss a served sanction case without penalty | ComplianceInvestigator, VendorUnitSupervisor |
| POST | `/sanction-cases/{id}/close` | Close the case from either fork branch: with the civil money penalty payment, or after disqualification was imposed | VendorUnitSupervisor |
| POST | `/_clock/set_current_utc` | Set the server's logical clock, which reads exactly 2026-08-01T00:00:00Z before any call and never falls back to real wall-clock time | SystemOperator |
| POST | `/_ops/risk-run` | Advance the risk epoch: recompute the persisted risk score for every non-terminal vendor, flag high-risk vendors, and escalate failed visits whose cure deadline lapsed | SystemOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_VENDOR_SCOPE_VIOLATION` | 403 |
| `ERR_FORBIDDEN_VISIT_TYPE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PEER_GROUP_NOT_FOUND` | 404 |
| `ERR_FOOD_CATEGORY_NOT_FOUND` | 404 |
| `ERR_FOOD_ITEM_NOT_FOUND` | 404 |
| `ERR_VENDOR_NOT_FOUND` | 404 |
| `ERR_PRICE_CYCLE_NOT_FOUND` | 404 |
| `ERR_PRICE_SUBMISSION_NOT_FOUND` | 404 |
| `ERR_PRICE_CEILING_NOT_FOUND` | 404 |
| `ERR_VISIT_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_CLAIM_LINE_NOT_FOUND` | 404 |
| `ERR_ADJUSTMENT_NOT_FOUND` | 404 |
| `ERR_SANCTION_CASE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_PEER_GROUP_CODE` | 409 |
| `ERR_DUPLICATE_FOOD_CATEGORY_CODE` | 409 |
| `ERR_DUPLICATE_UPC` | 409 |
| `ERR_DUPLICATE_CYCLE_CODE` | 409 |
| `ERR_INVALID_CYCLE_WINDOW` | 422 |
| `ERR_CYCLE_WINDOW_OVERLAP` | 409 |
| `ERR_STALE_CLAIM_VERSION` | 412 |
| `ERR_STALE_VENDOR_VERSION` | 412 |
| `ERR_INVALID_VENDOR_STATE` | 409 |
| `ERR_INVALID_CYCLE_STATE` | 409 |
| `ERR_INVALID_SUBMISSION_STATE` | 409 |
| `ERR_INVALID_VISIT_STATE` | 409 |
| `ERR_INVALID_CLAIM_STATE` | 409 |
| `ERR_INVALID_ADJUSTMENT_STATE` | 409 |
| `ERR_INVALID_SANCTION_STATE` | 409 |
| `ERR_CLAIM_NOT_ADJUDICATED` | 409 |
| `ERR_CLAIM_ALREADY_PAID` | 409 |
| `ERR_VENDOR_NOT_MONITORABLE` | 409 |
| `ERR_VENDOR_TRAINING_EXPIRED` | 409 |
| `ERR_OPEN_SANCTION_CASE_EXISTS` | 409 |
| `ERR_VENDOR_DISQUALIFIED` | 409 |
| `ERR_COMPLIANCE_BUY_NOT_WARRANTED` | 409 |
| `ERR_CMP_NOT_PERMITTED` | 409 |
| `ERR_CMP_ELECTION_WINDOW_EXPIRED` | 409 |
| `ERR_ELECTION_WINDOW_OPEN` | 409 |
| `ERR_DISQUALIFICATION_NOT_AVAILABLE` | 409 |
| `ERR_VISIT_DATE_IN_PAST` | 422 |
| `ERR_VISIT_BLACKOUT_CONFLICT` | 409 |
| `ERR_DUPLICATE_OBSERVATION` | 409 |
| `ERR_SUBMISSION_WINDOW_CLOSED` | 409 |
| `ERR_DUPLICATE_PRICE_SUBMISSION` | 409 |
| `ERR_REVISION_LIMIT_REACHED` | 409 |
| `ERR_PEER_GROUP_RETIRED` | 409 |
| `ERR_PRICE_SUBMISSIONS_INCOMPLETE` | 409 |
| `ERR_NO_PEER_GROUP_MATCH` | 422 |
| `ERR_NO_PUBLISHED_PRICE_CYCLE` | 409 |
| `ERR_REAUTHORIZATION_HOLD` | 409 |
| `ERR_REAUTH_WINDOW_NOT_OPEN` | 409 |
| `ERR_RECOUPMENT_EXCEEDS_PAYABLE` | 422 |
| `ERR_CMP_UNDERPAID` | 409 |
