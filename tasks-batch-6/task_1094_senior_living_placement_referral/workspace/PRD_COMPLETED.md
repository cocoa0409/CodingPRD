# Senior-Living Placement & Referral API — Product Requirements Document

## 1. Introduction

Families searching for senior housing rarely start with a shortlist. They start with a phone call or a web form at the moment a parent's needs outgrow the home they live in, and what follows is a compressed, emotionally loaded procurement exercise: understand the care level actually required, understand what the household can afford once veterans' benefits and insurance are factored in, tour a handful of communities that have an open unit at the right care level, sign a residency agreement, and move in. The placement platform described here sits in the middle of that process. It employs regionally assigned placement advisors who carry a bounded caseload, it maintains a contracted network of senior-living communities that pay a referral fee when a family they were introduced to actually moves in, and it must reconcile those fees to the cent — including clawing them back when a resident leaves within the contractual protection window.

This document specifies the REST API that runs the whole chain. Three properties make the system harder than a conventional CRM. First, money flows in both directions: a referral fee is estimated when a unit is reserved, recomputed and prorated when the resident actually moves in, accrued to a community's payable balance when the invoice is issued, negotiated down through a bounded dispute loop, paid, and possibly reversed by a clawback — every movement landing as an immutable ledger entry. Second, a single family action can ripple four levels deep: a community confirming a move-in reprices the fee, reserves and then occupies a unit, drafts an invoice, places the inquiry, withdraws every sibling match, releases the advisor's caseload slot, and cancels the tours booked on those withdrawn matches. Third, several parties with conflicting incentives touch the same rows, so the platform enforces segregation of duties — the advisor who wrote an assessment may not approve it, the counselor who issues a benefit estimate may not be the advisor assigned to the case, and the billing specialist who issues an invoice may never accept, dispute or pay it.

Correctness here is measured in reproducibility. Every date comparison, every scoring formula, every rounding step and every ordering decision is pinned in this specification so that two independent implementations, given the same request sequence, return byte-identical responses. Where the platform has a choice — round then sum, or sum then round; strict inequality or inclusive boundary — this document states which one applies and where.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API — without exception, including reads and including the logical-clock control endpoint — must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capacity in which that principal is acting. If either header is absent, or if `X-User-Role` is not one of the six role names enumerated below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This is the very first check the server performs; nothing else — not path-parameter resolution, not body validation — runs before it.

The six roles are `PlatformAdmin`, `Advisor`, `BenefitsCounselor`, `BillingSpecialist`, `CommunityManager` and `Family`. Once authentication succeeds, the server checks whether the acting role appears in the authorized-role list for the endpoint being called, as tabulated in §4. A role that is not listed there is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The six roles differ in how `X-User-ID` is interpreted, and this interpretation is what makes ownership checks meaningful:

- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but never compares it to any entity's `id`. `PlatformAdmin` is operations staff: it curates reference data (advisors, communities, unit pools), assigns and reassigns advisors, drives the logical clock, and reads every report.
- When `X-User-Role` is `Advisor`, `X-User-ID` is the `id` of the acting `Advisor` row; ownership checks on any resource that references an advisor compare the resource's advisor foreign key to `X-User-ID`. Concretely, an `Advisor` may act only on an inquiry whose `assigned_advisor_id` equals `X-User-ID`, and only on a tour whose `advisor_id` equals `X-User-ID`.
- When `X-User-Role` is `BenefitsCounselor`, `X-User-ID` is likewise the `id` of an `Advisor` row — the same identity space as `Advisor`, exercised in a financial-guidance capacity. The advisor row behind the header must have `is_va_certified` set to true; when it is false the request is rejected with `ERR_ADVISOR_NOT_VA_CERTIFIED` (HTTP 403).
- When `X-User-Role` is `BillingSpecialist`, `X-User-ID` is an opaque revenue-operations identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. This role issues, adjusts and voids referral invoices, and never accepts, disputes or pays them.
- When `X-User-Role` is `CommunityManager`, `X-User-ID` is the `id` of the acting `Community`; ownership checks on any resource that references a community compare the resource's `community_id` to `X-User-ID`. A `CommunityManager` may therefore act only on communities, unit pools, placements and referral invoices whose `community_id` equals `X-User-ID`.
- When `X-User-Role` is `Family`, `X-User-ID` is the `id` of the acting `Family`; a `Family` may act only on inquiries and placements reachable from the family whose `id` equals `X-User-ID` — that is, on an inquiry whose `family_id` equals `X-User-ID`, and on a placement whose inquiry belongs to that family.

Ownership violations by any of the four entity-backed roles (`Advisor`, `BenefitsCounselor`, `CommunityManager`, `Family`) are also reported as `ERR_UNAUTHORIZED` (HTTP 403); the API deliberately does not distinguish "you may not use this endpoint" from "this row is not yours". Read endpoints are open to all six roles, with the two report endpoints being the exception (see §4).

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100. `offset` defaults to 0 and may not be negative. A value outside those bounds is a request-shape failure and is rejected with `ERR_VALIDATION` (HTTP 422).

Results on every list endpoint are ordered by `created_at` ascending. Ties are broken by insertion order, which for this API is the order in which the rows were created within the same request or across requests. The `meta` block of a list response carries `limit` and `offset` as effectively applied, `total_count` giving the number of rows matching the filters before the page window is applied, and `has_more` which is true exactly when `offset` plus the number of rows returned in this page is strictly less than `total_count`.

Filters offered by individual list endpoints — the various foreign-key and status filters named in §4 — combine conjunctively: a request supplying two filters returns only the rows satisfying both. Filtering is applied first, then ordering, then the page window.

### 2.4. Common Resource Properties and the Logical Clock

Every stored resource carries a server-minted `id` that is a UUID with no type prefix and no embedded meaning, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp, refreshed on every mutation, and an integer `version` that begins at 1 when the row is created and increases by exactly 1 on each mutation that the specification says bumps it. Two entities are the exception: fee ledger entries and satisfaction surveys are immutable once written, so they carry only `id` and `created_at` — they have neither `updated_at` nor `version`. Clients should not expect a version field on those two, and no endpoint accepts one for them.

The platform runs on a **logical clock**, never on wall-clock time. Before any client moves it, the clock reads exactly `2026-05-01T00:00:00Z`, and it must never silently fall back to the real system time. An administrative test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the new `current_utc`. Every date- and time-sensitive rule in this document — inquiry urgency, tour scheduling windows, residency-confirmation waiting periods, survey eligibility, move-in and move-out date validity, and clawback windows — reads the logical clock, not the host machine's clock. Wherever this document says "the logical clock's current UTC calendar date", it means the calendar date (year-month-day in UTC) of the current logical instant.

### 2.5. Numeric Precision and Rounding

All monetary amounts are stored and returned as whole integer cents; there are no fractional cents anywhere in the system. Scores and indices are the only non-integer values. Unless a specific calculation says otherwise, every rounding step in this document uses **round half up** — a value exactly halfway between two representable results rounds to the larger magnitude. Priority scores, fit scores and composite satisfaction scores are carried to 2 decimal places; the two advisor load indices are carried to 4 decimal places. The individual calculations in §3 pin, for each formula, both the number of decimal places and the exact order in which rounding and summation occur, because two of them deliberately use opposite orders (one rounds each term before summing, the other sums at full precision and rounds once at the end).

### 2.6. Nested Resource Access and Referential Integrity

The URL surface is deliberately flat: no collection nests more than one level, and every write endpoint takes the identifiers of the rows it depends on in its request body rather than in the path. Children are always discovered through filtered list endpoints — for example, the invoice created by a move-in cascade is found by listing referral invoices filtered by `placement_id`, never through a nested collection path.

When an endpoint does carry a path parameter, that parameter is resolved first, before any body is inspected. If it fails to resolve to a stored row, the request is rejected with the not-found error specific to that resource type — `ERR_FAMILY_NOT_FOUND`, `ERR_ADVISOR_NOT_FOUND`, `ERR_COMMUNITY_NOT_FOUND`, `ERR_INVENTORY_NOT_FOUND`, `ERR_INQUIRY_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, `ERR_TOUR_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_GUIDANCE_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND` or `ERR_ASSIGNMENT_NOT_FOUND` — each at HTTP 404. Foreign-key identifiers supplied inside a request body are checked later, after body shape validation, and resolve to the same family of not-found errors (`ERR_FAMILY_NOT_FOUND`, `ERR_ADVISOR_NOT_FOUND`, `ERR_COMMUNITY_NOT_FOUND`, `ERR_INVENTORY_NOT_FOUND`, `ERR_INQUIRY_NOT_FOUND`, `ERR_MATCH_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`) at HTTP 404. `ERR_ASSESSMENT_NOT_FOUND` also stands in for the case where an operation needs the inquiry's needs assessment and none exists.

### 2.7. The Order in Which Requests Are Validated

Validation is strictly ordered, and the **first** failure encountered is the one returned; later checks never mask an earlier one. The ordering, from highest precedence downward, is:

1. Authentication — headers present and role recognized, else `ERR_UNAUTHENTICATED` (401).
2. Authorization by role — the acting role is listed for the endpoint, else `ERR_UNAUTHORIZED` (403).
3. Path-parameter existence — each path id resolves left-to-right, else the matching not-found error (404).
4. Request-body shape — every required field present, types correct, enum members legal, integers within their declared ranges, dates well-formed ISO 8601, and no unknown key that collides with a system- or computed-field name; any failure is `ERR_VALIDATION` (422).
5. Body foreign-key existence — each foreign-key id in the body resolves, else the matching not-found error (404).
6. Ownership — an entity-backed actor owns the resource it is acting on, else `ERR_UNAUTHORIZED` (403).
7. VA certification — for benefit-guidance creation, the acting advisor is VA-certified, else `ERR_ADVISOR_NOT_VA_CERTIFIED` (403).
8. Segregation of duties — for assessment review, an `Advisor` reviewer is not the author; for benefit guidance, the counselor is not the inquiry's assigned advisor. Either violation is `ERR_SEGREGATION_OF_DUTIES` (403).

Only after all of the above does the server evaluate the state-machine and business rules described in §3. Those downstream checks also have a pinned relative order wherever more than one can apply to the same endpoint; §3 states the order at each workflow, and the endpoint-specific orderings are summarized as they arise. In particular, for a state-transition endpoint the target row's current-state gate (yielding one of `ERR_INQUIRY_INVALID_STATE`, `ERR_ASSESSMENT_INVALID_STATE`, `ERR_MATCH_INVALID_STATE`, `ERR_TOUR_INVALID_STATE`, `ERR_PLACEMENT_INVALID_STATE` or `ERR_INVOICE_INVALID_STATE`, all at HTTP 409) is evaluated against that endpoint's own target resource. Two creation endpoints — match creation and benefit-guidance creation — do not take that generic inquiry-state gate; they instead take an assessment-approval gate described in §3, so the generic inquiry-state error never fires for them.

### 2.8. Optimistic Concurrency Control

Two creation endpoints guard a parent row with optimistic concurrency, because a second write against the same parent is legitimate business behaviour and cannot be rejected on uniqueness grounds alone; the only deterministic guard is a stale-version check.

Reserving a unit — the placement-creation endpoint — requires an `expected_inventory_version` field carrying the client's last observed `version` of the target `CommunityInventory`. If that value does not equal the inventory's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Because reservations, move-ins, cancellations and repricings all bump the inventory's version, this is the only reliable way to reject a writer whose view of the unit pool predates one of those events.

Issuing a benefit guidance — the benefit-guidance-creation endpoint — requires an `expected_assessment_version` field carrying the client's last observed `version` of the target `NeedsAssessment`. If that value does not equal the assessment's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). A new guidance supersedes the prior issued one and rewrites the assessment's affordability ceiling, so a counselor working from a stale assessment snapshot would otherwise silently overwrite a colleague's freshly issued estimate. In the validation order of §2.7 both of these version checks sit just after the target row's state gate and before the referential business checks. Endpoints not named in this subsection take no version field at all.

### 2.9. Cascades, Roll-ups and the Meaning of a Version Bump

Many operations touch more than one row. Whenever an operation mutates a resource, that resource's `updated_at` is refreshed and — for resources that carry one — its `version` is incremented by 1. Computed roll-up fields are recomputed synchronously in the same request, never on a delayed schedule: a community's `fee_balance_cents`, `satisfaction_survey_count` and `avg_satisfaction_score`; an advisor's `active_caseload_count`, `headcount_load_index` and `weighted_load_index`; an inventory's `reserved_units`, `occupied_units` and `available_units`; an inquiry's `match_count`; and an invoice's `net_recognized_fee_cents` are all kept current at the moment the triggering write commits. The larger multi-level cascades — a move-in that ripples through inventory, invoice, inquiry, sibling matches, caseload and tours, and a move-out that ripples through inventory, clawback and the ledger — are specified level by level in §3, and each level's `version` and `updated_at` effects apply as described there.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Advisors, Communities and Unit Pools

Operations staff seed the platform with three kinds of reference data before any family arrives. A placement advisor is registered with a `full_name`, a unique `email`, a `region_code` naming the market they serve, an optional `is_va_certified` flag that defaults to false, and a `caseload_capacity` that must be at least 1 and at most 25. On registration the advisor's `status` is set to `ACTIVE` and their three computed load fields — `active_caseload_count`, `headcount_load_index` and `weighted_load_index` — all start at 0. An advisor's `status` is one of `ACTIVE`, `PAUSED` or `INACTIVE`; only an `ACTIVE` advisor may receive new work. Operations staff may later update an advisor's `status`, `caseload_capacity` or `is_va_certified`; when `caseload_capacity` changes both load indices are recomputed immediately (see §3.9 for the index formulas), because the denominator of each index is the capacity.

A community is registered with a `name`, a `region_code`, a `contract_tier` that is one of `STANDARD`, `PREFERRED` or `PREMIER`, a `referral_fee_pct` giving the contracted share of one month's rent that the community pays as a referral fee (which must be greater than 0 and at most 1.00), a `tour_slot_capacity` between 1 and 20 governing how many overlapping scheduled tours the community can host, and a `quality_rating` between 0.0 and 5.0 used later in match scoring. A new community's `status` is `ACTIVE` and its three computed roll-ups — `fee_balance_cents`, `satisfaction_survey_count` and `avg_satisfaction_score` — start at 0. A community's `status` is one of `ACTIVE`, `SUSPENDED` or `TERMINATED`; moving it to `SUSPENDED` or `TERMINATED` blocks new matches, tours and placements at that community while leaving existing rows untouched. Operations staff may update a community's `status`, `contract_tier`, `referral_fee_pct`, `tour_slot_capacity` or `quality_rating`.

Each community owns one or more unit pools, one per care level. A `CommunityInventory` row is created with the owning `community_id`, a `care_level` drawn from `INDEPENDENT_LIVING`, `ASSISTED_LIVING`, `MEMORY_CARE` or `SKILLED_NURSING`, a `total_units` count of at least 0, and a published `monthly_rate_cents` greater than 0. At most one pool may exist per community-and-care-level combination; a second attempt for the same pair is rejected with `ERR_DUPLICATE_INVENTORY`. A new pool starts with `reserved_units` and `occupied_units` at 0, `available_units` equal to `total_units`, and `status` `OPEN` (the other value being `CLOSED`). The three unit counts are computed and reconciled continuously: `reserved_units` is the number of placements on the pool whose residency is `PENDING_MOVE_IN`, `occupied_units` is the number whose residency is `MOVED_IN` or `RESIDENT_CONFIRMED`, and `available_units` is `total_units` minus `reserved_units` minus `occupied_units`, never allowed to go below 0. Both platform staff and the owning community manager may create and edit pools. Editing may change `total_units`, `monthly_rate_cents` or `status`; every such edit recomputes `available_units` and bumps the pool's `version` by 1. An edit that would drop `total_units` below the sum of `reserved_units` and `occupied_units` is rejected with `ERR_INVENTORY_UNDER_ALLOCATED`, so the platform never oversells a pool that already has residents or reservations.

### 3.2. Opening an Inquiry and Scoring Its Priority

A family — the enquiring household — is registered with a `primary_contact_name`, a unique `email` that must contain an `@`, a `phone`, a `relationship_to_senior` that is one of `SELF`, `SPOUSE`, `ADULT_CHILD`, `OTHER_RELATIVE` or `FRIEND`, a two-letter `state_code`, the prospective resident's `senior_first_name`, and a `senior_age` that must be at least 55 and at most 120. Families may be registered by operations staff or by an advisor.

Opening an inquiry captures the `family_id`, the acquisition `origin` (`WEB`, `PHONE` or `PARTNER_REFERRAL`), the `region_code` the family is searching in, the `requested_care_level`, a `target_move_in_date` as an ISO 8601 calendar date, a `declared_budget_monthly_cents` greater than 0, and optional free-text `notes`. The `target_move_in_date` must be on or after the logical clock's current UTC calendar date; a past date is rejected with `ERR_MOVE_IN_DATE_INVALID`. A new inquiry begins in `NEW` status with `assigned_advisor_id` unset, `match_count` at 0, and `hold_reason`, `close_reason_code` all unset. The inquiry's lifecycle states are `NEW`, `ASSIGNED`, `ASSESSED`, `MATCHING`, `TOURING`, `PLACED`, `ON_HOLD` and `CLOSED_LOST`, with `PLACED` and `CLOSED_LOST` terminal.

At creation the inquiry's `priority_score` is computed once, frozen, and never recomputed. The score blends three normalized components. The **acuity component** is a fixed table lookup on `requested_care_level`: 22 for `INDEPENDENT_LIVING`, 57 for `ASSISTED_LIVING`, 86 for `MEMORY_CARE`, and 100 for `SKILLED_NURSING`. The **urgency component** measures how soon the move must happen: let the number of whole calendar days from today (the logical clock's current UTC date) to the `target_move_in_date` be the days-to-move, which validation guarantees is at least 0; the urgency component is 100 multiplied by the quantity (90 minus the smaller of days-to-move and 90), divided by 90, rounded half up to 2 decimals. In effect a move due today scores the full 100 on urgency, a move 90 or more days out scores 0, and the horizon that maps to zero urgency is 90 days. The **budget component** is 100 multiplied by `declared_budget_monthly_cents` divided by a reference of 600000 cents (i.e. a reference monthly budget of 6,000 dollars), rounded half up to 2 decimals, then capped at 100.00 so a lavish budget cannot exceed the ceiling. These three components are combined with weights of 0.45 on acuity, 0.35 on urgency and 0.20 on budget. The rounding order here is **round-then-sum**: each weighted term is first rounded to 2 decimals half up, and only then are the three rounded terms added; the resulting sum is reported exactly as that sum and is not rounded again. Only the three fields `requested_care_level`, `target_move_in_date` and `declared_budget_monthly_cents` of this one inquiry, plus the clock, feed the score — no other inquiry, assessment or match participates.

### 3.3. Assigning and Rebalancing Advisor Caseloads

A `NEW` inquiry has no advisor until operations staff assign one. Assignment moves the inquiry `NEW → ASSIGNED`, and the request body may name an `advisor_id` explicitly or omit it to let the platform choose. When an advisor is named explicitly, that advisor must be `ACTIVE` and serve the inquiry's `region_code`, otherwise the request is rejected with `ERR_ADVISOR_NOT_ELIGIBLE`; the advisor must also have room, meaning `active_caseload_count` strictly less than `caseload_capacity`, otherwise `ERR_ADVISOR_CASELOAD_FULL`. The generic state gate applies first — the inquiry must be in `NEW`, else `ERR_INQUIRY_INVALID_STATE`.

When `advisor_id` is omitted, the platform runs an auto-selection waterfall. First it filters to eligible advisors: those whose `status` is `ACTIVE`, whose `region_code` equals the inquiry's `region_code`, and whose `active_caseload_count` is strictly below their `caseload_capacity`. If that candidate pool is empty the request is rejected with `ERR_NO_ELIGIBLE_ADVISOR`. Otherwise the candidates are ranked by `weighted_load_index` ascending — the least acuity-loaded advisor first — with ties broken first by `active_caseload_count` ascending and then by `created_at` ascending (never by `id`), and the first candidate wins.

A successful assignment does five things: it sets the inquiry's `assigned_advisor_id` to the resolved advisor; it creates a `CaseloadAssignment` in `ACTIVE` status with `assigned_at` stamped from the logical clock; it increments that advisor's `active_caseload_count` by 1; it recomputes both of the advisor's load indices; and it increments the advisor's `version` by 1. A caseload assignment records `advisor_id`, `inquiry_id`, `assigned_at`, an initially-unset `released_at`, a `release_reason` (one of `PLACED`, `CLOSED_LOST` or `REASSIGNED`, unset while active) and a `status` of `ACTIVE`, `RELEASED` or `REASSIGNED`.

Reassignment moves a live inquiry from its current advisor to another. It is permitted while the inquiry is in `ASSIGNED`, `ASSESSED`, `MATCHING`, `TOURING` or `ON_HOLD` — and it does not change the inquiry's status, so it is a self-loop on whichever of those five states the inquiry currently holds; an inquiry outside that set yields `ERR_INQUIRY_INVALID_STATE`. The body carries `to_advisor_id`, which must differ from the inquiry's current `assigned_advisor_id`, else `ERR_VALIDATION` (422); this equality check is evaluated after the generic state gate above and before the target advisor's eligibility and caseload checks. The target advisor must be `ACTIVE`, serve the inquiry's `region_code` (else `ERR_ADVISOR_NOT_ELIGIBLE`) and have `active_caseload_count` strictly below `caseload_capacity` (else `ERR_ADVISOR_CASELOAD_FULL`). On success the inquiry's current `ACTIVE` caseload assignment moves to `REASSIGNED` with `release_reason` `REASSIGNED` and `released_at` set from the clock; the losing advisor's `active_caseload_count` is decremented by 1 and both its indices recomputed; a fresh `ACTIVE` assignment is created for the target advisor; the target's `active_caseload_count` is incremented by 1 and both its indices recomputed; and the inquiry's `assigned_advisor_id` is set to `to_advisor_id`.

### 3.4. The Needs Assessment and Its Review Cycle

Once an inquiry has an advisor, that advisor authors a needs-and-budget assessment. Creating an assessment captures the `inquiry_id`, three acuity scores — `adl_score` (activities of daily living), `cognitive_score` and `mobility_score`, each an integer from 0 to 10 — a `budget_monthly_cents` greater than 0, a `gross_monthly_income_cents` of at least 0, a `va_eligible` boolean, and a `marital_status` of `SINGLE`, `MARRIED` or `WIDOWED`. There may be at most one assessment per inquiry. The acting advisor becomes the author: `author_advisor_id` is taken from `X-User-ID`, and the row starts in `DRAFT` status. The assessment's states are `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED` and `APPROVED`, with `APPROVED` terminal. Fields that begin unset or zero include `revision_note`, `revision_count` (0), `benefit_offset_cents` (0) and `affordability_ceiling_cents` (0).

Every time the assessment lands in `DRAFT` — at creation and on every draft edit — the platform recomputes the `recommended_care_level` from the three acuity scores alone. Let the acuity total be the sum `adl_score` plus `cognitive_score` plus `mobility_score`, a number from 0 to 30. The branches are evaluated in this pinned order, first match wins: if the acuity total is at least 25 the recommendation is `SKILLED_NURSING`; otherwise if `cognitive_score` is at least 8 it is `MEMORY_CARE`; otherwise if the acuity total is at most 8 it is `INDEPENDENT_LIVING`; otherwise if the acuity total is at most 17 it is `ASSISTED_LIVING`; otherwise it is `MEMORY_CARE`. Note the ordering matters — a high cognitive score routes to memory care before the low-acuity independent-living branch is ever considered.

A draft assessment may be edited only by its author (`X-User-ID` equal to `author_advisor_id`) and only while it is in `DRAFT` or `REVISION_REQUESTED`; a non-author editor or any other state yields the respective ownership or state error. An edit accepts new values for any of `adl_score`, `cognitive_score`, `mobility_score`, `budget_monthly_cents`, `gross_monthly_income_cents`, `va_eligible` or `marital_status`, recomputes `recommended_care_level`, and — when the row was in `REVISION_REQUESTED` — returns it to `DRAFT` and clears `revision_note`. The author submits the draft for peer review, moving it `DRAFT → SUBMITTED`; submission is likewise author-only and requires the current state to be `DRAFT`.

Peer review of a `SUBMITTED` assessment carries a `decision` of `APPROVE` or `REQUEST_REVISION` and an optional `revision_note`. Segregation of duties governs the reviewer: when the reviewing actor's role is `Advisor`, their `X-User-ID` must not equal the assessment's `author_advisor_id`, else `ERR_SEGREGATION_OF_DUTIES`; a `PlatformAdmin` reviewer is not bound by that constraint. The assessment must be in `SUBMITTED`, else `ERR_ASSESSMENT_INVALID_STATE`. An `APPROVE` decision moves the assessment `SUBMITTED → APPROVED`, sets its `affordability_ceiling_cents` (see below), and moves the linked inquiry `ASSIGNED → ASSESSED` (bumping the inquiry's `version`). A `REQUEST_REVISION` decision moves the assessment `SUBMITTED → REVISION_REQUESTED`, stores the `revision_note`, and increments `revision_count` by 1. The author then edits the row — which closes the cycle `DRAFT → SUBMITTED → REVISION_REQUESTED → DRAFT` — and may resubmit.

The **affordability ceiling** is computed on approval and recomputed whenever the assessment's benefit offset changes. It is the assessment's `budget_monthly_cents` multiplied by a stretch factor of 1.10, rounded half up to whole cents, plus the current `benefit_offset_cents`. The benefit offset is the `estimated_monthly_benefit_cents` of the single benefit guidance for this assessment whose status is `ISSUED` (superseded guidances are excluded), or 0 when no issued guidance exists. The rounding applies to the stretched budget before the benefit offset is added.

### 3.5. Financial and VA-Benefit Guidance

Benefit guidance is issued by a VA-certified counselor to estimate what a household can draw from a funding instrument. Creating a guidance captures the `inquiry_id`, a `benefit_type` of `VA_AID_ATTENDANCE`, `VA_SURVIVOR_PENSION`, `LTC_INSURANCE` or `BRIDGE_LOAN`, and the `expected_assessment_version` optimistic-concurrency guard described in §2.8. The server resolves the inquiry's assessment and records `assessment_id` and, from `X-User-ID`, the `counselor_advisor_id`; the row's computed fields `unreimbursed_medical_cents`, `countable_income_cents` and `estimated_monthly_benefit_cents` are filled by the estimate below, and its `status` starts as `ISSUED` (the only other value being `SUPERSEDED`).

Several gates guard this endpoint, in the order of §2.7 after the shared checks: the acting advisor must be VA-certified (`ERR_ADVISOR_NOT_VA_CERTIFIED`); the counselor's `X-User-ID` must not equal the inquiry's `assigned_advisor_id`, enforcing that the guidance author is not the case advisor (`ERR_SEGREGATION_OF_DUTIES`); the `expected_assessment_version` must match (`ERR_STALE_VERSION`, 412); the inquiry must have an `APPROVED` assessment, else `ERR_ASSESSMENT_NOT_APPROVED`, and once approved the inquiry's status must additionally be one of `ASSESSED`, `MATCHING`, `TOURING` or `ON_HOLD`, a violation of that second clause yielding `ERR_INQUIRY_INVALID_STATE`; and the assessment's `va_eligible` must be true, else `ERR_GUIDANCE_NOT_ELIGIBLE`.

The estimate runs as a single forward pass of four steps; the dependency looks circular — the household's ceiling depends on the award and the award depends on the care cost — so the order is fixed. **Step 1** takes the projected care cost to be exactly the assessment's `budget_monthly_cents` (never the affordability ceiling that step 4 writes), and sets `unreimbursed_medical_cents` to the larger of 0 and that projected care cost minus 5% of `gross_monthly_income_cents` (the 5% figure rounded half up to whole cents before subtraction). **Step 2** sets `countable_income_cents` to the larger of 0 and `gross_monthly_income_cents` minus `unreimbursed_medical_cents`. **Step 3** selects a monthly cap by benefit key: for `VA_AID_ATTENDANCE` with `marital_status` `MARRIED` the cap is 276000 cents; for `VA_AID_ATTENDANCE` with `marital_status` `SINGLE` or `WIDOWED` it is 233000; for `VA_SURVIVOR_PENSION` it is 149800; for `LTC_INSURANCE` it is 200000; for `BRIDGE_LOAN` it is 120000. The `estimated_monthly_benefit_cents` is the larger of 0 and the smaller of the cap and the quantity (cap minus `countable_income_cents`). **Step 4** writes the assessment's `benefit_offset_cents` to that estimate and recomputes the assessment's `affordability_ceiling_cents` per §3.4.

Creating a guidance is also a three-level cascade. At level 1 the new guidance is created `ISSUED`, and any prior guidance for the same `assessment_id` that was `ISSUED` moves to `SUPERSEDED`. At level 2 the assessment's `benefit_offset_cents` becomes the new estimate, its `affordability_ceiling_cents` is recomputed, and its `version` is incremented by 1. At level 3, because the ceiling changed, every match of the inquiry whose status is `PROPOSED` or `SHORTLISTED` has its `fit_score` recomputed against the new ceiling (see §3.6 for the fit formula).

### 3.6. Matching a Community to an Inquiry

With an approved assessment in hand, the advisor proposes communities. Creating a match captures the `inquiry_id`, the `community_id` and the proposed `care_level`. The match snapshots and computes several fields: `quoted_monthly_rate_cents` is copied from the resolved unit pool's `monthly_rate_cents` at creation and never re-snapshotted; `fit_score` is computed as below; `status` starts at `PROPOSED`; `decline_reason_code` is unset; and `tour_round` starts at 0. The match states are `PROPOSED`, `SHORTLISTED`, `TOUR_SCHEDULED`, `TOURED`, `SELECTED`, `DECLINED` and `WITHDRAWN`, with `DECLINED` and `WITHDRAWN` terminal.

Match creation is heavily gated, and its checks run in this order after the shared existence and shape checks. The referenced community must be `ACTIVE`, else `ERR_COMMUNITY_NOT_ACTIVE`. The inquiry must have an `APPROVED` assessment (else `ERR_ASSESSMENT_NOT_APPROVED`), and once approved its status must be one of `ASSESSED`, `MATCHING` or `TOURING`, a violation yielding `ERR_INQUIRY_INVALID_STATE` — this replaces the generic inquiry-state gate for this endpoint. No non-terminal match may already exist for the same inquiry-and-community pair: if a match for that `(inquiry_id, community_id)` exists whose status is anything other than `DECLINED` or `WITHDRAWN`, the request is rejected with `ERR_DUPLICATE_MATCH`. A unit pool with `status` `OPEN` must exist for the community and the proposed care level, else `ERR_CARE_LEVEL_UNAVAILABLE`. Finally the fiscal gate: the resolved pool's `monthly_rate_cents` must be at most the inquiry's assessment `affordability_ceiling_cents` — equality is accepted — else `ERR_BUDGET_EXCEEDED`. On the first match created for an inquiry, the inquiry moves `ASSESSED → MATCHING`, its `match_count` is incremented by 1 and its `version` bumped; subsequent matches keep the inquiry in `MATCHING` and still increment `match_count`.

The **fit score** blends four factors and — unlike the priority score — sums at full precision and rounds once at the end. Resolve the unique unit pool for the match's community and care level, the inquiry's `recommended_care_level` (call it the recommendation), the inquiry's `affordability_ceiling_cents` (the ceiling), and the match's snapshotted `quoted_monthly_rate_cents` (the rate). **Care fit** is 100 when the match's `care_level` equals the recommendation; 60 when the match's care level sits exactly one step above the recommendation on the ordering `INDEPENDENT_LIVING`(1), `ASSISTED_LIVING`(2), `MEMORY_CARE`(3), `SKILLED_NURSING`(4); and 0 otherwise. **Budget fit** works from the ratio of rate to ceiling: if that ratio exceeds 1.0 the budget fit is 0.00; if it is at most 0.85 the budget fit is 100.00; otherwise it is 100 minus 300 times the amount by which the ratio exceeds 0.85, floored at 0.0 and rounded half up to 2 decimals. **Quality fit** is 20 times the community's `quality_rating`, rounded half up to 2 decimals. **Availability fit** is the smaller of 100.00 and 20 times the pool's live `available_units`. The four factors are weighted 0.40 on care fit, 0.35 on budget fit, 0.15 on quality fit and 0.10 on availability fit; the weighted terms are summed at full precision and the total is rounded half up once to 2 decimals. The rate is the creation-time snapshot, while `available_units` and `quality_rating` are read live at each evaluation, so a later benefit guidance or inventory movement can shift the fit score of a still-open match.

Advisors and families drive the match through its shortlist-and-tour cycle. Shortlisting moves a `PROPOSED` match to `SHORTLISTED`, and also returns a `TOURED` match to `SHORTLISTED` when a family wants a repeat visit — the same action serves both the `PROPOSED → SHORTLISTED` and `TOURED → SHORTLISTED` edges, disambiguated by the match's current state. Declining records a `reason_code` into `decline_reason_code`, moves the match to `DECLINED`, and decrements the inquiry's `match_count` by 1; declining is permitted from `PROPOSED`, `SHORTLISTED` or `TOURED`. Selecting moves a `TOURED` match to `SELECTED` and additionally requires the match's community to still be `ACTIVE` (else `ERR_COMMUNITY_NOT_ACTIVE`). Each of these transitions rejects a match not in its from-set with `ERR_MATCH_INVALID_STATE`.

### 3.7. Scheduling and Running Tours

A tour is booked against a `SHORTLISTED` match. The request supplies the `match_id`, a `scheduled_start` and `scheduled_end` as ISO 8601 UTC instants, and a `mode` of `IN_PERSON` or `VIRTUAL`. The server copies `advisor_id` from the match's inquiry's `assigned_advisor_id` and `community_id` from the match's `community_id`. A new tour starts `SCHEDULED` with `outcome_rating` and `cancel_reason_code` unset; the tour states are `SCHEDULED`, `COMPLETED`, `CANCELLED` and `NO_SHOW`, the last three terminal.

Booking is guarded in order. The match must be `SHORTLISTED` (else `ERR_MATCH_INVALID_STATE`) and its community `ACTIVE` (else `ERR_COMMUNITY_NOT_ACTIVE`). The time window must be well-formed: `scheduled_end` strictly after `scheduled_start`, the duration between 30 and 180 minutes inclusive, and `scheduled_start` at or after the logical clock's current instant — any of these failing yields `ERR_TOUR_OUTSIDE_HOURS`. Then two overlap checks. The **community tour-slot** check counts the community's scheduled tours whose closed interval `[scheduled_start, scheduled_end]` intersects the candidate's closed interval — where two closed intervals intersect when the existing start is at or before the candidate end and the candidate start is at or before the existing end, so tours that merely touch at an endpoint do count as intersecting — and that count must be strictly less than the community's `tour_slot_capacity`, else `ERR_TOUR_SLOT_CONFLICT`. The **advisor calendar** check looks at every scheduled tour already held by the inquiry's assigned advisor and rejects the candidate when the candidate start is earlier than the existing end plus a buffer and the existing start is earlier than the candidate end plus that buffer; the buffer is 45 minutes when either tour is `IN_PERSON` and 0 minutes when both are `VIRTUAL`. The comparison is strict, so a gap of exactly the buffer is accepted; a violation is `ERR_ADVISOR_SCHEDULE_CONFLICT`.

Booking a tour also advances the surrounding workflow: the match moves `SHORTLISTED → TOUR_SCHEDULED` and its `tour_round` is incremented by 1, and on the very first tour scheduled on any match of the inquiry, the inquiry moves `MATCHING → TOURING` (bumping the inquiry's `version`). Completing a tour supplies an `outcome_rating` from 1 to 5, may be done only by the tour's own advisor (`X-User-ID` equal to `advisor_id`), moves the tour `SCHEDULED → COMPLETED` and moves its match `TOUR_SCHEDULED → TOURED`. Cancelling a scheduled tour records a `reason_code` into `cancel_reason_code`, moves the tour `SCHEDULED → CANCELLED`, returns its match `TOUR_SCHEDULED → SHORTLISTED`, and releases the community tour slot the tour occupied. Marking a no-show is advisor-only (again `X-User-ID` equal to `advisor_id`), moves the tour `SCHEDULED → NO_SHOW`, likewise returns the match to `SHORTLISTED` and releases the slot. All three of these post-schedule actions require the tour to be `SCHEDULED`, else `ERR_TOUR_INVALID_STATE`. The shortlist-tour loop `SHORTLISTED → TOUR_SCHEDULED → SHORTLISTED` may repeat, and `tour_round` records how many times it ran.

### 3.8. Pausing, Resuming and Closing an Inquiry

An advisor may pause a search at the family's request, supplying a `reason` that is stored as the inquiry's `hold_reason`. A hold is permitted from `MATCHING` or `TOURING` and moves the inquiry to `ON_HOLD`; an inquiry in any other state yields `ERR_INQUIRY_INVALID_STATE`. When the hold is placed from `TOURING`, it also cancels every one of the inquiry's tours that is still `SCHEDULED` — setting each such tour's `cancel_reason_code` to `INQUIRY_ON_HOLD` — and returns each of those tours' matches `TOUR_SCHEDULED → SHORTLISTED`. Resuming a paused inquiry clears its `hold_reason` and always returns it to `MATCHING`, regardless of whether the hold came from `MATCHING` or `TOURING`; resume requires the inquiry to be `ON_HOLD`. Both hold and resume may be driven by the assigned advisor or by operations staff.

Closing an inquiry as lost records a `reason_code` into `close_reason_code` and moves the inquiry to `CLOSED_LOST`. Close is permitted while the inquiry is in `ASSIGNED`, `ASSESSED`, `MATCHING`, `TOURING` or `ON_HOLD`, and only when the inquiry has no placement whose residency is `PENDING_MOVE_IN`, `MOVED_IN` or `RESIDENT_CONFIRMED`. On close, every match of the inquiry whose status is `PROPOSED`, `SHORTLISTED`, `TOUR_SCHEDULED` or `TOURED` moves to `WITHDRAWN`; every still-`SCHEDULED` tour on those withdrawn matches moves to `CANCELLED` with `cancel_reason_code` `MATCH_WITHDRAWN`; and the inquiry's `ACTIVE` caseload assignment moves to `RELEASED` with `release_reason` `CLOSED_LOST`, decrementing the owning advisor's `active_caseload_count` by 1 and recomputing both its load indices. Each withdrawn match also decrements the inquiry's `match_count` by 1.

### 3.9. Advisor Load Indices

Two load indices summarize how full an advisor's caseload is, and both are recomputed on every event that changes `active_caseload_count` — assignment, reassignment, and every cascade that releases an assignment — as well as being freshly evaluated on any read of a single advisor or of the caseload report. Both indices consider only the advisor's caseload assignments whose status is `ACTIVE`; released and reassigned rows are excluded. The **headcount load index** is the count of active assignments divided by the advisor's `caseload_capacity`, rounded half up to 4 decimals; it treats every active assignment as exactly 1.0 regardless of the underlying inquiry's acuity or urgency, and it is the variant used as the hard eligibility gate (an advisor is assignable only while `active_caseload_count` is strictly below `caseload_capacity`). The **weighted load index** sums the frozen `priority_score` of each active assignment's inquiry, divides by the product of `caseload_capacity` and 100, and rounds half up to 4 decimals; because each case is weighted by its priority over 100, a caseload of low-priority cases produces a materially lower index than the headcount variant. The weighted index is the ranking key of the auto-selection waterfall in §3.3, compared at the stored 4-decimal precision.

### 3.10. Reserving a Unit and Confirming the Move-In

A placement realizes a `SELECTED` match. Creating one captures the `match_id`, the `inventory_id` of the unit pool the reservation draws from, an `agreed_move_in_date` calendar date, a `contracted_monthly_rate_cents` greater than 0, and the `expected_inventory_version` optimistic-concurrency guard from §2.8. From the match the server copies `inquiry_id`, `community_id` and `care_level`. A new placement starts with `residency_status` `PENDING_MOVE_IN` and `billing_status` `NOT_INVOICED`; its `actual_move_in_date`, `actual_care_level`, `final_fee_cents`, `move_out_date` and `days_resided` are unset, and `clawback_amount_cents` is 0. The residency axis runs `PENDING_MOVE_IN`, `MOVED_IN`, `RESIDENT_CONFIRMED`, `MOVED_OUT` and `CANCELLED` (the last two terminal); the billing axis runs `NOT_INVOICED`, `INVOICE_DRAFTED`, `INVOICED`, `PAID`, `CLAWED_BACK` and `VOIDED` (the last two terminal) and advances independently of residency, so a row can sit at, say, residency `MOVED_IN` with billing `PAID`, or residency `RESIDENT_CONFIRMED` with billing `INVOICE_DRAFTED`.

Placement creation is gated in order: the referenced match must be `SELECTED` (else `ERR_MATCH_INVALID_STATE`), and this match-state gate is checked first; the referenced community must be `ACTIVE` (else `ERR_COMMUNITY_NOT_ACTIVE`); the `expected_inventory_version` must match the pool's current `version` (else `ERR_STALE_VERSION`, 412); the inquiry must not already have a placement whose residency is anything other than `CANCELLED` or `MOVED_OUT`, else `ERR_PLACEMENT_EXISTS`; and the chosen pool must have `available_units` of at least 1, else `ERR_NO_UNITS_AVAILABLE`. On success the platform computes `estimated_fee_cents` via the estimated variant of the referral-fee formula (§3.11), increments the pool's `reserved_units` by 1, recomputes `available_units`, and increments the pool's `version` by 1.

Confirming a move-in is the community manager's action and the platform's deepest cascade. The body supplies the `actual_move_in_date` and the `actual_care_level` actually contracted (which may differ from the reserved care level). The placement must be `PENDING_MOVE_IN` (else `ERR_PLACEMENT_INVALID_STATE`), the acting community manager must own the placement (`X-User-ID` equal to the placement's `community_id`), and the `actual_move_in_date` must be on or before the logical clock's current UTC calendar date, else `ERR_MOVE_IN_DATE_INVALID`. The cascade then runs four levels deep. **Level 1** records `actual_move_in_date` and `actual_care_level`, computes `final_fee_cents` via the final variant of the referral-fee formula, moves the pool's counts (decrement `reserved_units` by 1, increment `occupied_units` by 1, recompute `available_units`, bump `version`), and creates a `DRAFT` referral invoice whose `final_fee_cents` is seeded from the placement, moving the placement's billing axis `NOT_INVOICED → INVOICE_DRAFTED`. **Level 2**, caused by level 1, moves the linked inquiry `TOURING → PLACED`. **Level 3**, caused by that placement, moves every match of the inquiry still in `PROPOSED`, `SHORTLISTED`, `TOUR_SCHEDULED` or `TOURED` to `WITHDRAWN` (each decrementing `match_count` by 1), and moves the inquiry's `ACTIVE` caseload assignment to `RELEASED` with `release_reason` `PLACED` and `released_at` from the clock, decrementing the owning advisor's `active_caseload_count` by 1 and recomputing both its load indices. **Level 4**, caused by the level-3 withdrawals, moves every still-`SCHEDULED` tour on those withdrawn matches to `CANCELLED` with `cancel_reason_code` `MATCH_WITHDRAWN`, releasing each such community tour slot.

After move-in the advisor confirms the resident is still in place. Residency confirmation moves the placement `MOVED_IN → RESIDENT_CONFIRMED` and is allowed only once the logical clock's current UTC calendar date is at least the `actual_move_in_date` plus 14 days (the residency-confirmation waiting period); an earlier attempt is rejected with `ERR_RESIDENCY_CONFIRM_TOO_EARLY`. Confirmation leaves the billing axis untouched, so it may fire while billing is `NOT_INVOICED`, `INVOICE_DRAFTED`, `INVOICED` or `PAID`.

A reservation that never converts can be cancelled by the advisor or the owning community manager. Cancellation moves the placement `PENDING_MOVE_IN → CANCELLED`, releases the held unit (decrement `reserved_units` by 1, recompute `available_units`, bump the pool's `version`), and — deliberately — leaves the underlying match in `SELECTED` so a replacement placement can be created. A cancel on a placement not in `PENDING_MOVE_IN` yields `ERR_PLACEMENT_INVALID_STATE`.

### 3.11. The Referral Fee: Estimated and Final Variants

The referral fee has a shared component structure evaluated with a per-variant rate, care level and proration ratio. Compute a `base_cents` as the rate multiplied by the community's `referral_fee_pct` multiplied by the ratio, rounded half up to whole cents. Compute a care-premium as the rate multiplied by a care-level premium percentage — 0.00 for `INDEPENDENT_LIVING`, 0.05 for `ASSISTED_LIVING`, 0.12 for `MEMORY_CARE`, 0.15 for `SKILLED_NURSING` — multiplied by the ratio, rounded half up to whole cents. Compute a tier bonus as the already-rounded `base_cents` multiplied by the quantity (the community's contract-tier multiplier minus 1.00), where the multiplier is 1.00 for `STANDARD`, 1.10 for `PREFERRED` and 1.25 for `PREMIER`, again rounded half up to whole cents. Each of these three components is rounded to whole cents **before** they are summed, and the tier bonus is deliberately computed from the rounded base rather than an unrounded product. Sum the three components, then clamp the total to lie between a floor of 150000 cents and a ceiling of 900000 cents — the clamp is applied last, to the summed total only.

The **estimated variant** runs at placement creation and is stored in `estimated_fee_cents`. It uses the match's `quoted_monthly_rate_cents` as the rate, the match's `care_level` as the level, and a ratio of exactly 1.0 — no proration at all, so the estimate always books a full first month. The **final variant** runs at move-in confirmation, is stored in `final_fee_cents`, and is copied onto the created referral invoice; it also re-runs whenever a disputed invoice is adjusted. It uses the placement's `contracted_monthly_rate_cents` as the rate and the placement's `actual_care_level` as the level, and it prorates: let occupied days be the smaller of 30 and the quantity (31 minus the day-of-month of `actual_move_in_date`), and let the proration ratio be occupied days divided by 30. Because of proration, an identical rate and care level still yield a different final fee from the estimate whenever the move-in day of month is not the 1st.

### 3.12. Invoicing, Disputes, Payment and Void

The invoice created by the move-in cascade begins in `DRAFT` and is discovered only by listing referral invoices filtered by `placement_id` or `community_id`. An invoice carries `placement_id`, `community_id`, a `final_fee_cents` seeded from the placement and replaced on adjustment, a `paid_amount_cents` starting at 0, a computed `net_recognized_fee_cents`, a `status`, a `dispute_reason`, a `claimed_rate_cents`, an `adjustment_count` starting at 0, and an `issued_at` timestamp. Invoice states are `DRAFT`, `ISSUED`, `DISPUTED`, `ACCEPTED`, `PAID`, `VOIDED` and `CLAWED_BACK`, the last two terminal.

A billing specialist issues a `DRAFT` invoice: the invoice must itself be `DRAFT`, else `ERR_INVOICE_INVALID_STATE`, and this invoice-state gate is evaluated first; only then is the linked placement's residency required to be `MOVED_IN` or `RESIDENT_CONFIRMED`, else `ERR_PLACEMENT_NOT_MOVED_IN`. Issuing moves the invoice `DRAFT → ISSUED`, appends an `ACCRUAL` ledger entry of positive `final_fee_cents`, increases the community's `fee_balance_cents` by `final_fee_cents`, recomputes the invoice's `net_recognized_fee_cents`, sets `issued_at` to the logical clock, and moves the placement's billing axis `INVOICE_DRAFTED → INVOICED`.

The community manager who owns the invoice then accepts, disputes or pays it — never the billing specialist. Accepting moves an `ISSUED` invoice to `ACCEPTED`. Disputing an `ISSUED` invoice records a `dispute_reason` and a `claimed_rate_cents`, moves it `ISSUED → DISPUTED`, and is permitted only while `adjustment_count` is strictly below the dispute-round cap of 2, else `ERR_DISPUTE_LIMIT_EXCEEDED`. Billing then adjusts the disputed invoice: adjustment supplies an `adjusted_rate_cents` and a `note`, recomputes `final_fee_cents` from that rate via the final referral-fee variant, appends an `ADJUSTMENT` ledger entry equal to the new `final_fee_cents` minus the previous one, moves the community's `fee_balance_cents` by that same signed delta, increments `adjustment_count` by 1, refreshes `issued_at`, and moves the invoice `DISPUTED → ISSUED` — closing the negotiation cycle `ISSUED → DISPUTED → ISSUED`, which the cap of 2 bounds. Paying requires the invoice to be `ACCEPTED` and the community manager to own it, and the body's `amount_cents` must exactly equal the invoice's `final_fee_cents`, else `ERR_INVOICE_AMOUNT_MISMATCH`. Payment appends a `PAYMENT` ledger entry of negative `amount_cents`, decreases the community's `fee_balance_cents` by that amount, records `paid_amount_cents`, moves the invoice `ACCEPTED → PAID`, and moves the placement's billing axis `INVOICED → PAID`.

Voiding is the billing specialist's compensating action for an issue, permitted while the invoice is `ISSUED` or `DISPUTED`. It supplies a `reason_code`, appends a `WRITE_OFF` ledger entry of negative `final_fee_cents`, decreases the community's `fee_balance_cents` by `final_fee_cents`, recomputes `net_recognized_fee_cents`, moves the invoice to `VOIDED`, and moves the placement's billing axis `INVOICED → VOIDED`. Any of these invoice actions attempted from a state outside its from-set yields `ERR_INVOICE_INVALID_STATE`.

### 3.13. Move-Out, Clawback and the Fee Ledger

A community reports a move-out (operations staff may also drive it) with a `move_out_date` and a `reason_code`. The placement's residency must be `MOVED_IN` or `RESIDENT_CONFIRMED` (else `ERR_PLACEMENT_INVALID_STATE`), and `move_out_date` must be on or after the `actual_move_in_date` and on or before the logical clock's current UTC calendar date, else `ERR_MOVE_OUT_DATE_INVALID`. The move-out is a three-level clawback cascade. **Level 1** sets `move_out_date` and `days_resided` (the whole calendar days from `actual_move_in_date` to `move_out_date`), and moves the pool's counts (decrement `occupied_units` by 1, recompute `available_units`, bump the pool's `version`); the placement's residency moves to `MOVED_OUT`. **Level 2** computes `clawback_amount_cents`. A clawback exists only where a fee was actually recognised: if the placement has no referral invoice whose status is `ISSUED`, `ACCEPTED` or `PAID` — because the invoice is still `DRAFT`, or already `VOIDED` or `CLAWED_BACK` — then `clawback_amount_cents` is 0, no ledger entry is written, and the billing axis is left untouched. Otherwise the clawback percentage is 1.00 when `days_resided` is at most 30, 0.50 when `days_resided` is at most 90 (but more than 30), and 0.00 beyond 90; both boundaries are inclusive, so exactly 30 days is a full clawback and exactly 90 days is a half clawback. The `clawback_amount_cents` is the placement's `final_fee_cents` multiplied by that percentage, rounded half up to whole cents. When it is greater than 0 the referral invoice moves to `CLAWED_BACK` and the placement's billing axis moves to `CLAWED_BACK`. **Level 3**, caused by a positive clawback, appends a `CLAWBACK` ledger entry whose `amount_cents` is the negative of `clawback_amount_cents`, decreases the community's `fee_balance_cents` by `clawback_amount_cents`, and recomputes the invoice's `net_recognized_fee_cents`.

Every fee movement lands as an immutable `FeeLedgerEntry`, which carries `invoice_id`, `placement_id`, `community_id`, an `entry_type` of `ACCRUAL`, `ADJUSTMENT`, `PAYMENT`, `CLAWBACK` or `WRITE_OFF`, a signed `amount_cents` (positive increases what the community owes), a computed `balance_after_cents`, and a human-readable `reason`. The ledger is append-only: entries are never deleted or edited. A community's `fee_balance_cents` is the running total of `amount_cents` over all its entries, processed in ascending `created_at` order; when two entries share a `created_at` they are processed in the order their triggering transitions fired within the request, never by `id`. Each entry's `balance_after_cents` records the running total immediately after it is applied. An invoice's `net_recognized_fee_cents` is the sum of `amount_cents` over that invoice's entries whose `entry_type` is `ACCRUAL`, `ADJUSTMENT`, `CLAWBACK` or `WRITE_OFF` — deliberately excluding `PAYMENT` entries, which move cash rather than recognized revenue. All ledger arithmetic is in whole cents with no rounding.

### 3.14. Satisfaction Surveys and Reporting

A family submits one post-move-in satisfaction survey per placement. The survey supplies the `placement_id`, an `nps_score` from 0 to 10, a `care_rating` from 1 to 5 and a `value_rating` from 1 to 5; the server copies `respondent_family_id` from the placement's inquiry's `family_id` and `community_id` from the placement, and computes `days_after_move_in` as the whole days from the placement's `actual_move_in_date` to the logical clock's current UTC date. Only one survey may exist per placement, a duplicate yielding `ERR_DUPLICATE_SURVEY`, and this duplicate check is evaluated before the eligibility window; a survey may then be submitted only once the current date is at least the `actual_move_in_date` plus 30 days (the survey-eligibility window), else `ERR_SURVEY_TOO_EARLY` — a placement that has not yet recorded an `actual_move_in_date` likewise fails with `ERR_SURVEY_TOO_EARLY`. Surveys are immutable and never withdrawn.

The **composite score** normalizes the three answers to a 0-to-100 scale — `nps_score` times 10, `care_rating` times 20, `value_rating` times 20 — and weights them 0.40 on the normalized NPS, 0.35 on the normalized care rating and 0.25 on the normalized value rating, rounding the weighted sum half up once to 2 decimals. Each survey insert also rolls up to the community: `satisfaction_survey_count` becomes the count of that community's surveys, and `avg_satisfaction_score` becomes the mean of their `composite_score` values, rounded half up to 2 decimals (0 when there are no surveys). There is no status filter on the roll-up because surveys are never withdrawn.

Two reports close the picture. The **advisor-caseload report** returns, for one advisor or a whole region, the `advisor_id`, `active_caseload_count`, `caseload_capacity`, both `headcount_load_index` and `weighted_load_index` (freshly evaluated at read time), and a `total_active_assignments` count. The **community-referrals report** returns, for a community, its `community_id`, a `placement_count`, and the accrued, payment, clawback and write-off totals (returned as `accrued_fee_cents`, `payment_cents`, `clawback_cents` and `write_off_cents` respectively) alongside `fee_balance_cents` and `avg_satisfaction_score`, giving billing and community operators a single reconciled view of accrued, paid, clawed-back and net recognized fees.

## 4. Endpoint Definitions

The table below is a routing summary only; the full request body, response payload and side effects of each endpoint are specified in the §3 narratives and must be reconstructed from there. Resource-creation endpoints return HTTP 201 with the created resource; state transitions and other modifications return HTTP 200 with the updated resource; reads return HTTP 200. All endpoints require the `X-User-ID` and `X-User-Role` headers described in §2.1.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /_clock/set_current_utc | Test-driving endpoint: moves the server's logical clock to an explicit UTC instant | PlatformAdmin |
| POST | /advisors | Register a placement advisor | PlatformAdmin |
| GET | /advisors/{advisor_id} | Read one advisor, including both load-index variants | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /advisors | List advisors with filtering and pagination | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| PATCH | /advisors/{advisor_id} | Update advisor availability, capacity or VA certification | PlatformAdmin |
| POST | /communities | Register a senior-living community and its referral contract terms | PlatformAdmin |
| GET | /communities/{community_id} | Read one community, including its fee balance and satisfaction roll-up | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /communities | List communities with filtering and pagination | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| PATCH | /communities/{community_id} | Update contract standing or commercial terms of a community | PlatformAdmin |
| POST | /inventories | Create a care-level unit pool for a community | PlatformAdmin, CommunityManager |
| GET | /inventories/{inventory_id} | Read one unit pool, including its current version for optimistic concurrency | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /inventories | List unit pools; filter by community_id to find a community's inventory | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| PATCH | /inventories/{inventory_id} | Resize, reprice or close a unit pool | PlatformAdmin, CommunityManager |
| POST | /families | Register the enquiring household | PlatformAdmin, Advisor |
| GET | /families/{family_id} | Read one family | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /families | List families with filtering and pagination | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| POST | /inquiries | Open a placement inquiry for a family | PlatformAdmin, Advisor, Family |
| GET | /inquiries/{inquiry_id} | Read one inquiry, including its frozen priority_score and current version | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /inquiries | List inquiries; filter by family_id or assigned_advisor_id to walk the foreign keys | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| POST | /inquiries/{inquiry_id}/assign | Assign an advisor to a NEW inquiry | PlatformAdmin |
| POST | /inquiries/{inquiry_id}/reassign | Move a live inquiry from its current advisor to another advisor | PlatformAdmin |
| POST | /inquiries/{inquiry_id}/hold | Pause a search at the family's request | Advisor, PlatformAdmin |
| POST | /inquiries/{inquiry_id}/resume | Resume a paused search; the inquiry always lands back on MATCHING | Advisor, PlatformAdmin |
| POST | /inquiries/{inquiry_id}/close | Close an inquiry as lost | Advisor, PlatformAdmin |
| POST | /assessments | Create the needs and budget assessment for an inquiry; the acting advisor becomes its author | Advisor |
| GET | /assessments/{assessment_id} | Read one assessment, including affordability_ceiling_cents and its current version for optimistic concurrency | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /assessments | List assessments; filter by inquiry_id or author_advisor_id to walk the foreign keys | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| PATCH | /assessments/{assessment_id} | Edit a DRAFT or REVISION_REQUESTED assessment; a REVISION_REQUESTED row returns to DRAFT | Advisor |
| POST | /assessments/{assessment_id}/submit | Submit a DRAFT assessment for peer review | Advisor |
| POST | /assessments/{assessment_id}/review | Peer-review a SUBMITTED assessment | Advisor, PlatformAdmin |
| POST | /matches | Propose a community to an inquiry with an approved assessment | Advisor |
| GET | /matches/{match_id} | Read one match, including its fit_score | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /matches | List matches; filter by inquiry_id or community_id to walk the foreign keys | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| POST | /matches/{match_id}/shortlist | Shortlist a PROPOSED match, or return a TOURED match to the shortlist for a repeat visit | Advisor, Family |
| POST | /matches/{match_id}/decline | Decline a match on the family's behalf | Advisor, Family |
| POST | /matches/{match_id}/select | Select a TOURED match as the family's choice | Advisor |
| POST | /tours | Book a tour for a SHORTLISTED match against the assigned advisor's calendar and the community's tour-slot capacity | Advisor |
| GET | /tours/{tour_id} | Read one tour | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /tours | List tours; filter by match_id, advisor_id or community_id to walk the foreign keys | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| POST | /tours/{tour_id}/complete | Record a completed tour and the family's reaction | Advisor |
| POST | /tours/{tour_id}/cancel | Cancel a scheduled tour and free its community slot | Advisor, Family |
| POST | /tours/{tour_id}/no-show | Record that the family did not attend | Advisor |
| POST | /placements | Reserve a unit for a SELECTED match | Advisor |
| GET | /placements/{placement_id} | Read one placement, including both state axes and both fee variants | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /placements | List placements; filter by inquiry_id, community_id, match_id or inventory_id to walk the foreign keys | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| POST | /placements/{placement_id}/confirm-move-in | Community confirms the resident moved in; drives the four-level cascade and drafts the referral invoice | CommunityManager |
| POST | /placements/{placement_id}/confirm-residency | Advisor confirms the resident is still in place after the residency-confirmation window | Advisor |
| POST | /placements/{placement_id}/move-out | Community reports a move-out; drives the three-level clawback cascade | CommunityManager, PlatformAdmin |
| POST | /placements/{placement_id}/cancel | Cancel a reservation that never converted; releases the held unit | Advisor, CommunityManager |
| GET | /referral-invoices/{invoice_id} | Read one referral invoice | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /referral-invoices | List referral invoices; filter by placement_id or community_id | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| POST | /referral-invoices/{invoice_id}/issue | Issue a DRAFT invoice to the community and accrue the fee | BillingSpecialist |
| POST | /referral-invoices/{invoice_id}/accept | Community accepts an issued invoice | CommunityManager |
| POST | /referral-invoices/{invoice_id}/dispute | Community disputes an issued invoice, claiming a different monthly rate | CommunityManager |
| POST | /referral-invoices/{invoice_id}/adjust | Billing re-prices a disputed invoice and re-issues it, closing one negotiation round | BillingSpecialist |
| POST | /referral-invoices/{invoice_id}/pay | Community pays an accepted invoice in full | CommunityManager |
| POST | /referral-invoices/{invoice_id}/void | Compensating action for issue: writes the accrual back off and voids the invoice | BillingSpecialist |
| GET | /ledger-entries | List fee ledger entries; filter by invoice_id, placement_id or community_id | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /ledger-entries/{entry_id} | Read one fee ledger entry | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| POST | /benefit-guidances | Issue a VA / financial benefit estimate for an inquiry | BenefitsCounselor |
| GET | /benefit-guidances/{guidance_id} | Read one benefit guidance | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /benefit-guidances | List benefit guidances; filter by inquiry_id, assessment_id or counselor_advisor_id | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| POST | /surveys | Family submits the post-move-in satisfaction survey | Family |
| GET | /surveys/{survey_id} | Read one satisfaction survey | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /surveys | List satisfaction surveys; filter by placement_id, respondent_family_id or community_id | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /caseload-assignments | List caseload assignments; filter by advisor_id or inquiry_id | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /caseload-assignments/{assignment_id} | Read one caseload assignment | PlatformAdmin, Advisor, BenefitsCounselor, BillingSpecialist, CommunityManager, Family |
| GET | /reports/advisor-caseload | Caseload report: both load-index variants side by side for one advisor or a whole region | PlatformAdmin, Advisor |
| GET | /reports/community-referrals | Referral report: accrued, paid, clawed-back and net recognized fees for one community | PlatformAdmin, BillingSpecialist, CommunityManager |

## 5. Error Code Catalogue

The trigger conditions for each error are specified in the §2 and §3 narratives, not here. This catalogue fixes only the machine-readable identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_ADVISOR_NOT_VA_CERTIFIED | 403 |
| ERR_VALIDATION | 422 |
| ERR_FAMILY_NOT_FOUND | 404 |
| ERR_ADVISOR_NOT_FOUND | 404 |
| ERR_COMMUNITY_NOT_FOUND | 404 |
| ERR_INVENTORY_NOT_FOUND | 404 |
| ERR_INQUIRY_NOT_FOUND | 404 |
| ERR_ASSESSMENT_NOT_FOUND | 404 |
| ERR_MATCH_NOT_FOUND | 404 |
| ERR_TOUR_NOT_FOUND | 404 |
| ERR_PLACEMENT_NOT_FOUND | 404 |
| ERR_INVOICE_NOT_FOUND | 404 |
| ERR_GUIDANCE_NOT_FOUND | 404 |
| ERR_SURVEY_NOT_FOUND | 404 |
| ERR_LEDGER_ENTRY_NOT_FOUND | 404 |
| ERR_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_INQUIRY_INVALID_STATE | 409 |
| ERR_ASSESSMENT_INVALID_STATE | 409 |
| ERR_MATCH_INVALID_STATE | 409 |
| ERR_TOUR_INVALID_STATE | 409 |
| ERR_PLACEMENT_INVALID_STATE | 409 |
| ERR_INVOICE_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_COMMUNITY_NOT_ACTIVE | 409 |
| ERR_ASSESSMENT_NOT_APPROVED | 409 |
| ERR_PLACEMENT_NOT_MOVED_IN | 409 |
| ERR_GUIDANCE_NOT_ELIGIBLE | 409 |
| ERR_DUPLICATE_INVENTORY | 409 |
| ERR_DUPLICATE_MATCH | 409 |
| ERR_PLACEMENT_EXISTS | 409 |
| ERR_DUPLICATE_SURVEY | 409 |
| ERR_CARE_LEVEL_UNAVAILABLE | 409 |
| ERR_ADVISOR_NOT_ELIGIBLE | 409 |
| ERR_NO_ELIGIBLE_ADVISOR | 409 |
| ERR_DISPUTE_LIMIT_EXCEEDED | 409 |
| ERR_TOUR_OUTSIDE_HOURS | 422 |
| ERR_TOUR_SLOT_CONFLICT | 409 |
| ERR_ADVISOR_SCHEDULE_CONFLICT | 409 |
| ERR_MOVE_IN_DATE_INVALID | 422 |
| ERR_RESIDENCY_CONFIRM_TOO_EARLY | 409 |
| ERR_SURVEY_TOO_EARLY | 409 |
| ERR_MOVE_OUT_DATE_INVALID | 422 |
| ERR_ADVISOR_CASELOAD_FULL | 409 |
| ERR_BUDGET_EXCEEDED | 409 |
| ERR_NO_UNITS_AVAILABLE | 409 |
| ERR_INVENTORY_UNDER_ALLOCATED | 409 |
| ERR_INVOICE_AMOUNT_MISMATCH | 422 |

