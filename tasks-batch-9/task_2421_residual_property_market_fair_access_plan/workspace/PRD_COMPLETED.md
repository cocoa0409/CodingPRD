# Residual Property Fair Access Plan API — Product Requirements Document

## 1. Introduction

Every state that has watched its coastal, wildland or seismic property markets tighten eventually stands up a residual market: a Fair Access to Insurance Requirements (FAIR) Plan that writes the dwellings no voluntary carrier will touch. The plan is not a competitor. It is an insurer of last resort, and almost every rule in it exists to keep it that way — applicants must document that the voluntary market turned them down, the perils it covers are deliberately narrower than a standard homeowners form, its filed rates are held **above** the surveyed voluntary average so that it cannot undercut the private market, and voluntary carriers are given a standing incentive to take policies back out of the plan.

This document specifies the REST API that runs such a plan end to end. It carries an application from a producer's desk through documented declination evidence, condition-based property inspection with mandatory remediation, regulator-approved rating, and binding into a one-year policy term. It then carries that policy through renewal, mid-term cancellation with a refund calculation, and depopulation via take-out offers that the policyholder — not the plan and not the carrier — elects on. Behind all of it sits the machinery a residual market needs to stay solvent: per-territory catastrophe exposure caps that progressively restrict and then close binding, and an assessment mechanism that apportions losses in excess of plan reserves across the member insurers, net of the depopulation credits those members earned by taking policies out.

Two structural properties shape the whole surface and should be read before anything else. First, a policy carries **two independent state dimensions on the same record** — a coverage dimension and a depopulation dimension — and most operations move exactly one of them. Second, three pairs of steps are **separated by person, not by role**: the regulator who approves a rate filing may not be the analyst who filed it, the underwriter who waives an improvement requirement may not be the inspector who raised it, and the underwriter who binds a policy may not be the underwriter who advanced the application through eligibility review. All resources are mounted under the `/fair-plan` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. Plan Participants, Authentication and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. If either header is absent, or present but empty or whitespace-only, or if `X-User-Role` is not one of the eight declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not authorized for the operation being attempted, the rejection is `ERR_FORBIDDEN_ROLE` (HTTP 403).

The eight declared roles are `PlanAdmin`, `Producer`, `Underwriter`, `Inspector`, `RateAnalyst`, `Regulator`, `MemberInsurerUser`, and `Policyholder`.

Three of these roles are **entity-backed**, meaning `X-User-ID` is the identifier of a persisted row and is compared against ownership fields on the resources being touched:

- When `X-User-Role` is `Producer`, `X-User-ID` is the `id` of the acting `Producer` record; ownership checks on any resource that references a `Producer` compare the resource's producer foreign-key field to `X-User-ID`. A producer therefore acts only on applications whose `producer_id` equals `X-User-ID`, and only on improvement requirements reachable from those applications.
- When `X-User-Role` is `MemberInsurerUser`, `X-User-ID` is the `id` of the acting `MemberInsurer` record; ownership checks compare the resource's `member_insurer_id` to `X-User-ID`. That operator may therefore only create or withdraw take-out offers on behalf of its own carrier, and may only settle assessment allocations charged to its own carrier.
- When `X-User-Role` is `Policyholder`, `X-User-ID` is the `id` of the acting `Applicant` record — the identifier returned when the named-insured record was created. Ownership checks compare the `applicant_id` of the policy behind an offer to `X-User-ID`.

The remaining five roles are **opaque**: `X-User-ID` is an operator identifier not tied to any persisted entity, and the server never compares it to an entity's `id`. It is, however, recorded where the workflow needs an audit trail and where segregation of duties is enforced. When `X-User-Role` is `Underwriter`, the identifier is recorded as `eligibility_reviewer_user_id` on the application whose eligibility that underwriter advanced or declined. When `X-User-Role` is `Inspector`, it is recorded as `inspector_user_id` on the inspection that inspector completed. When `X-User-Role` is `RateAnalyst`, it is recorded as `filed_by_user_id` on the rate filing created. When `X-User-Role` is `Regulator`, it is recorded as `reviewed_by_user_id` on the filing reviewed. When `X-User-Role` is `PlanAdmin`, the identifier is not persisted on any record; plan administrators are trusted operators of membership, territory, producer-agreement, assessment, sweep and clock functions.

When an entity-backed role passes role authorization but the ownership comparison fails, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership gate guards seven operations: submitting an application, recording a declination on an application, submitting remediation evidence for an improvement requirement, creating a take-out offer against a policy, electing on a take-out offer, withdrawing a take-out offer, and paying an assessment allocation.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by twenty upper-case alphanumeric characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, and it is the one timestamp in the system read from the host's real UTC clock rather than from the logical clock of §2.6, because it is envelope metadata rather than a business comparison or a derived record field.
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

List responses are paginated with two query parameters. `limit` is the maximum number of rows returned; it defaults to 10, its minimum accepted value is 1 and its maximum is 100. `offset` is the number of rows skipped before the page begins; it defaults to 0 and its minimum accepted value is 0. A `limit` below 1 or above 100, or a negative `offset`, is a schema violation and is rejected with `ERR_INVALID_REQUEST` (HTTP 400), as is a `limit` or `offset` whose supplied text is not a well-formed integer.

Unless a specific list states otherwise, rows are returned sorted by their `created_at` timestamp in ascending order; because the logical clock only moves when an administrator moves it, many rows share an identical `created_at`, and those ties are broken by the order in which the server minted the records, earliest first.

Every list response includes `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope. `total_count` is the number of rows matching the filters before pagination is applied, and `has_more` is true exactly when rows remain beyond the current page.

Most lists additionally accept domain filters, which are named in the workflow narratives of §3. A filter whose value is not a member of the underlying field's enumeration is likewise rejected with `ERR_INVALID_REQUEST`.

### 2.4. Record Identity, Audit Fields and Version Counters

Every persisted record carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC string with three fractional digits.

Most records additionally carry two mutation-tracking fields: `updated_at`, an ISO 8601 UTC timestamp with three fractional digits refreshed on every change to the record, and `version`, an integer that begins at 1 when the record is created and increases by exactly one on every mutation of that record. The records carrying all four fields are member insurers, producers, applicants, catastrophe zones, properties, applications, inspections, improvement requirements, rate filings, policies, take-out offers, assessment events and assessment allocations.

There is one deliberate exception. A declination record is an immutable piece of eligibility evidence: it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from a declination record entirely.

A recomputation of a derived field counts as a mutation. When a bind pushes a territory's aggregate insured value up, or a clearance decrements an inspection's open-requirement counter, the touched record's `updated_at` is refreshed and its `version` increases by one even though no client sent a request naming that record.

### 2.5. Money, Rates and Rounding Discipline

All monetary amounts in this system are integers denominated in **whole cents**, and every field whose name ends in `_cents` is such an integer. There are no fractional cents anywhere in a stored value or a response body. Wherever a monetary quantity is produced by multiplication or division, the result is rounded to a whole number of cents using the **round-half-up** convention (a value exactly halfway between two cents rounds away from zero, upward). Where a calculation is specified as a sequence of steps, the rounding happens at **each** named step before the next step consumes the result; a reader must not defer rounding to the end.

Ratios are a separate class. The three ratio fields — a territory's `concentration_ratio`, a rate filing's `differential_pct`, and an application's `voluntary_market_comparison_pct` — are decimal numbers rounded half up to **four** decimal places. Threshold comparisons against them are made on the rounded four-decimal value, and every such threshold in this specification is inclusive unless the text says otherwise.

Percentage-weight fields — a member's `market_share_pct` and `written_premium_share_pct`, and the `basis_weight_pct` snapshotted onto an allocation — are decimal percentages carried to two decimal places, on a scale where 100.00 means the whole market; the server stores and echoes the numeric value the client supplied as it stands rather than re-rounding it to two places. Both member weights must be at least 0.00 and no greater than 100.00, and a value outside that range is a schema violation rejected with `ERR_INVALID_REQUEST`.

Commission is expressed in basis points. A producer's `commission_rate_bps` is an integer count of hundredths of a percent, so converting it into a multiplier means dividing by 10,000.

### 2.6. The Logical Clock, Dates and Window Arithmetic

The server does not read wall-clock time for any business comparison. It maintains a **logical clock** whose value at process start is exactly `2026-08-01T00:00:00Z`, and it never falls back to real time. A plan administrator may move the clock forward or backward by supplying a `to_iso8601` instant; the response body reports the resulting `current_utc`. Every deadline, lookback window, staleness test, term comparison and derived timestamp in this document is evaluated against the logical clock.

Some fields are full instants and some are calendar dates. `submitted_at`, `approved_to_bind_at`, `bind_deadline_at`, `ordered_at`, `completed_at`, `due_at`, `cleared_at`, `elected_at`, `paid_at` and `election_deadline_at` are instants. `e_and_o_expiry_date`, `agreement_effective_date`, `declined_on`, `scheduled_for`, a rate filing's `effective_date`, a policy's `effective_date` and `expiration_date`, and `cancellation_date` are calendar dates in `YYYY-MM-DD` form; comparisons involving them are made at day granularity, and day arithmetic on them counts whole days.

A policy term is a **half-open interval** running from its `effective_date` up to but not including its `expiration_date`. That is what makes a successor term starting exactly on the day a predecessor term ends legal rather than overlapping.

### 2.7. Territory Exposure Posture and the Conservation of Insured Value

A catastrophe zone is a rating and exposure territory. It is created with a unique `code`, a dominant `peril` drawn from `HURRICANE`, `WILDFIRE` and `EARTHQUAKE`, an `exposure_cap_cents` that must be greater than zero, and an optional `restricted_min_condition_score` between 0 and 100 inclusive that defaults to 70 when the creator omits it.

The plan's live exposure in a territory is the derived field `aggregate_insured_value_cents`: the sum of `exposure_value_cents` over every policy attributed to that territory whose `coverage_status` is either `BOUND` or `IN_FORCE`. A policy is attributed to a territory through its property's `cat_zone_id`. Policies in `CANCELLED`, `EXPIRED` or `TAKEN_OUT` are excluded from the sum entirely — that exclusion is what makes the exposure figure exactly conserved: whatever a bind adds, the matching termination removes.

From that sum the plan derives `concentration_ratio`, the aggregate insured value divided by the exposure cap, rounded half up to four decimals. The territory's derived `status` is then read off a three-rung ladder: the status is `CLOSED` when the concentration ratio is at least 1.0000, otherwise `RESTRICTED` when the ratio is at least 0.8500, otherwise `OPEN`. Both thresholds are inclusive, so a ratio of exactly 0.8500 is `RESTRICTED` and a ratio of exactly 1.0000 is `CLOSED`. A newly created territory starts with an aggregate insured value of 0, a concentration ratio of 0.0 and a status of `OPEN`.

The ladder is walked in both directions. Any operation that adds a policy to the `BOUND`-or-`IN_FORCE` set, and any operation that removes one from it, recomputes the aggregate, recomputes the ratio, re-derives the status, and increments the territory's `version` by one. A territory that had climbed to `CLOSED` therefore descends back through `RESTRICTED` to `OPEN` as cancellations, expirations and take-outs release exposure.

### 2.8. Segregation of Duties Across the Rating and Underwriting Chain

Three separations are enforced, and every one of them is keyed on `X-User-ID` rather than on `X-User-Role` — two different people holding the same role satisfy the rule, while one person switching roles does not evade it. All three failures carry the same code, `ERR_SEGREGATION_OF_DUTIES` (HTTP 409):

- The regulator reviewing a rate filing must have an `X-User-ID` different from that filing's `filed_by_user_id`.
- The underwriter waiving an improvement requirement must have an `X-User-ID` different from the `inspector_user_id` recorded on the parent inspection.
- The underwriter binding a policy must have an `X-User-ID` different from the `eligibility_reviewer_user_id` recorded on the application being bound.

### 2.9. Stale-Version Protection on Territory and Assessment Writes

Two write operations are protected by optimistic concurrency control against the `version` of a **parent** record, because in both cases the state machine alone cannot tell a legitimate second write from a write made against a record the caller has not re-read.

Creating a rate filing requires a non-optional `expected_zone_version` field carrying the client's last observed `version` of the target `CatastropheZone`. If that number does not equal the zone's current `version`, the filing is rejected with `ERR_STALE_VERSION` (HTTP 412). This protection is necessary precisely because several filings may legitimately sit in `FILED` status on the same territory and package at once, so no state precondition can catch the problem; what makes the write wrong is that the zone's posture moved underneath the analyst — an approval superseded the prior approved filing, or a bind, cancellation, expiry or take-out re-derived the zone status — after the version the request carries.

Running the allocation for an assessment event requires a non-optional `expected_assessment_event_version` field carrying the client's last observed `version` of the target `AssessmentEvent`. A mismatch with the event's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Here too the state machine cannot help: a re-run from `ALLOCATED` is a legitimate supersede that abates the prior pending allocations and rebuilds the set from current member weights, so the second caller cannot be turned away on state grounds. Only the stale version distinguishes an intentional supersede from an administrator acting on an allocation set they have not observed.

No other endpoint accepts a version field, and no other endpoint performs a version check.

### 2.10. Cascade Discipline

A single request in this system routinely mutates several records. The rule is that **every** record touched by a cascade is mutated in full: its own fields are written, its `updated_at` is refreshed, and its `version` increments by one. Cascades run to completion within the request that triggered them; there is no deferred or eventual reconciliation, and a read issued immediately afterward observes every hop.

The deepest cascades in the plan are worth naming up front, because an implementation that stops at the first hop will look correct on the resource in the response body and wrong everywhere else. Clearing or waiving the last open improvement requirement mutates the requirement, then the parent inspection, then the application. Accepting a take-out offer mutates the offer, then the offering member carrier, then the policy, then the producer, then the catastrophe zone. Paying the final outstanding assessment allocation mutates the allocation, then the parent assessment event, then every member carrier that held an allocation on that event. Binding a policy mutates the new policy, the producer, the catastrophe zone and the application.

### 2.11. Request Validation Order and Path Resolution

When a path contains several identifiers, they are resolved strictly **left to right**, and the first one that does not resolve produces `ERR_NOT_FOUND` (HTTP 404) before any identifier to its right is examined. Foreign keys supplied in a request body are resolved after path identifiers, and also produce `ERR_NOT_FOUND`.

Where more than one rule could reject a request, the plan evaluates them in a fixed precedence so that the reported error is deterministic. The full ladder, from highest precedence to lowest, is:

1. **Authentication.** Both headers present and `X-User-Role` a declared role, or `ERR_UNAUTHENTICATED` (401).
2. **Role authorization.** The caller's role is listed for the operation, or `ERR_FORBIDDEN_ROLE` (403).
3. **Request schema.** Required body fields present, enum values recognized, integers non-negative, dates well-formed ISO-8601, condition scores between 0 and 100 inclusive, `limit` between 1 and 100, `offset` at least 0, `evidence_reference` a non-empty string, and no client-supplied `cancel_reason` of `TAKEOUT_ELECTION`. Otherwise `ERR_INVALID_REQUEST` (400).
4. **Path identifier existence,** left to right, or `ERR_NOT_FOUND` (404).
5. **Body foreign-key existence** — `cat_zone_id`, `applicant_id`, `property_id`, `application_id` and `member_insurer_id` — or `ERR_NOT_FOUND` (404); where one request body carries two of them they are resolved in exactly that listed order, so opening an application that names both an unknown `applicant_id` and an unknown `property_id` reports the applicant. This rung guards property registration, application creation, declination recording, rate filing creation, policy binding, take-out offer creation and assessment-event creation.
6. **Entity-backed ownership,** or `ERR_NOT_RESOURCE_OWNER` (403), on the seven operations named in §2.1.
7. **Parent version freshness,** or `ERR_STALE_VERSION` (412), on rate filing creation and the assessment allocation run.
8. **Uniqueness** of a member's `naic_code`, a producer's `license_number`, a territory's `code` and an applicant's `email`, or `ERR_DUPLICATE_IDENTIFIER` (409), on the four corresponding create operations.
9. **Declination uniqueness** — no existing declination record already pairs this `application_id` with this `member_insurer_id` — or `ERR_DUPLICATE_DECLINATION` (409).
10. Application submittability: status `DRAFT` or `ELIGIBILITY_HELD`, or `ERR_APPLICATION_NOT_SUBMITTABLE` (409).
11. Application reviewability: status `SUBMITTED` or `ELIGIBILITY_HELD`, or `ERR_APPLICATION_NOT_REVIEWABLE` (409).
12. Inspection orderability: application status `INSPECTION_PENDING` or `IMPROVEMENTS_REQUIRED`, or `ERR_INSPECTION_NOT_ORDERABLE` (409).
13. Inspection completability: the inspection's `result` is `PENDING`, or `ERR_INSPECTION_ALREADY_COMPLETED` (409).
14. Requirement state: `OPEN` for evidence submission, `EVIDENCE_SUBMITTED` for clearance, and either `OPEN` or `EVIDENCE_SUBMITTED` for waiver, or `ERR_REQUIREMENT_STATE_INVALID` (409).
15. Filing reviewability: the filing's `status` is `FILED`, or `ERR_FILING_NOT_REVIEWABLE` (409).
16. Application bindability: status `APPROVED_TO_BIND`, or `ERR_APPLICATION_NOT_BINDABLE` (409).
17. Policy coverage state: `coverage_status` is `IN_FORCE`, with cancellation additionally accepting `BOUND` when the supplied `cancel_reason` is `PLAN_INITIATED`, or `ERR_POLICY_NOT_IN_FORCE` (409). This rung guards cancellation, renewal and take-out offer creation.
18. Offer availability: the policy's `depopulation_status` is `NOT_OFFERED`, or `ERR_OFFER_ALREADY_OUTSTANDING` (409).
19. Offer liveness: the offer's `status` is `OUTSTANDING`, or `ERR_OFFER_NOT_OUTSTANDING` (409), on election and withdrawal.
20. Assessment state: `DRAFT` or `ALLOCATED` for an allocation run, `ALLOCATED` for invoicing, and one of `DRAFT`, `ALLOCATED` or `INVOICED` for cancellation, or `ERR_ASSESSMENT_STATE_INVALID` (409).
21. Allocation payability: the allocation's `status` is `PENDING` and its parent event's `status` is `INVOICED`, or `ERR_ALLOCATION_NOT_PAYABLE` (409).
22. Producer agreement state: `PENDING` for agreement execution, `APPOINTED` for suspension, `SUSPENDED` for reinstatement, and either `APPOINTED` or `SUSPENDED` for termination, or `ERR_PRODUCER_STATUS_INVALID` (409).
23. Segregation of duties on filing review, then on requirement waiver, then on policy binding — all three `ERR_SEGREGATION_OF_DUTIES` (409), in that relative order.
24. Waivability by severity: the requirement's `severity` is `MINOR`, or `ERR_MAJOR_REQUIREMENT_NOT_WAIVABLE` (422).
25. Territory not closed for binding or renewal, or `ERR_ZONE_CLOSED` (409).
26. Restricted-territory eligibility for binding or renewal, or `ERR_ZONE_RESTRICTED_INELIGIBLE` (409).
27. Producer appointment, or `ERR_PRODUCER_NOT_APPOINTED` (409), on application creation, application submission, binding and renewal.
28. Member standing, or `ERR_MEMBER_NOT_ACTIVE` (409), on take-out offer creation and allocation payment.
29. Availability of an approved rate, or `ERR_NO_APPROVED_RATE` (409), on application submission, binding and renewal.
30. Declination sufficiency at review time, or `ERR_INSUFFICIENT_DECLINATIONS` (422), when an eligibility review advances an application.
31. Peril availability, or `ERR_PERIL_NOT_OFFERED` (422), on application creation.
32. Coverage limit ceilings, or `ERR_COVERAGE_LIMIT_EXCEEDED` (422), on application creation and renewal.
33. Vacancy eligibility at bind, or `ERR_VACANT_PROPERTY_INELIGIBLE` (422).
34. Inspection freshness at bind, or `ERR_INSPECTION_STALE` (422).
35. Bind window, or `ERR_BIND_DEADLINE_PASSED` (422).
36. Term non-overlap on the property, or `ERR_POLICY_TERM_OVERLAP` (409), on binding and renewal.
37. Filing quiet-window separation, or `ERR_FILING_WINDOW_CONFLICT` (409), when a filing is approved.
38. Election window, or `ERR_ELECTION_WINDOW_CLOSED` (422).
39. Non-competition rate floor, or `ERR_RATE_BELOW_VOLUNTARY_FLOOR` (422), on rate filing creation.
40. Offer comparability, or `ERR_OFFER_NOT_COMPARABLE` (422).
41. Territory exposure headroom, or `ERR_ZONE_EXPOSURE_CAP_EXCEEDED` (422), on binding and renewal.
42. Losses in excess of reserves, or `ERR_LOSSES_WITHIN_RESERVES` (422), on an allocation run.
43. A non-empty assessable member set, or `ERR_NO_ASSESSABLE_MEMBERS` (422), on an allocation run.
44. Exact settlement, or `ERR_PAYMENT_AMOUNT_MISMATCH` (422), on allocation payment.

## 3. Business Logic & Workflows

### 3.1. Plan Foundations: Member Carriers, Territories and Producer Agreements

Before a single application can be written, a plan administrator must populate three registries. The first is the roster of **member insurers** — the voluntary-market carriers that participate in the plan, share its assessment burden, and are entitled to depopulate it. Admitting a carrier records its legal `name`, its regulator-issued `naic_code` (conventionally five characters, and unique across all carriers — only the uniqueness is enforced, and any non-empty string is accepted whatever its length), its statewide homeowners `market_share_pct`, and its share of statewide written premium as `written_premium_share_pct`. A newly admitted carrier begins in `status` `ACTIVE`, with `takeout_credit_count` at 0 and `cumulative_assessed_cents` at 0.

Membership standing then walks a one-way path: `ACTIVE`, then `RUNOFF`, then `WITHDRAWN`, which is terminal. An administrator moves a carrier along that path, or restates its assessment basis weights, through the same membership update operation, which accepts an optional new `status`, an optional new `market_share_pct` and an optional new `written_premium_share_pct`; a supplied `status` that is neither the carrier's current status nor its single legal successor — any backward or path-skipping move — is a schema violation rejected with `ERR_INVALID_REQUEST` (HTTP 400), while restating a carrier to the status it already holds is accepted as a no-op, and every accepted update refreshes `updated_at` and increments `version` by one even when no field value actually changes. Moving `ACTIVE → RUNOFF` requires the carrier to currently be `ACTIVE`; a carrier in run-off **remains assessable** and stays inside the eligible member set used by allocation runs, but it may no longer create take-out offers. Moving `RUNOFF → WITHDRAWN` requires the carrier to currently be `RUNOFF`; from that point forward the carrier is excluded from the eligible member set, and any new declination record naming it is created with `verified` set to false. Each of these moves increments the carrier's `version` by one. Restating weights is deliberately *not* retroactive: allocation rows already created are never re-weighted, and only a superseding allocation run re-reads the current weights. Administrators, regulators and any member-carrier operator may read a carrier's record including its credit and assessment counters — a read is not one of the ownership-gated operations of §2.1, so an operator is not confined to its own carrier here; administrators and regulators may page the roster, optionally filtered by `status`. Two reverse lookups hang off a carrier: the declinations it has issued, and the assessment allocations charged to it (the latter filterable by allocation `status`).

The second registry is **catastrophe territories**, whose creation fields and derived exposure posture are specified in §2.7. Three reverse lookups hang off a territory: the properties located in it, the rate filings written against it — narrowable by filing `status` and by `peril_package` — and the assessment events triggered by losses in it, narrowable by event `status`.

The third registry is **producers**. Registering a licensed agent records `full_name`, a `license_number` unique across all producers, a `commission_tier` of either `STANDARD` or `PREFERRED`, and the agent's errors-and-omissions expiry as `e_and_o_expiry_date`. Registration leaves the agreement unexecuted: `agreement_status` is `PENDING`, `commission_rate_bps` is 0, `agreement_effective_date` is null, and the conserved `ytd_commission_cents` is 0. Executing the producer agreement — which requires the agreement to currently be `PENDING` — carries an `agreement_effective_date` in the request, moves `agreement_status` from `PENDING` to `APPOINTED`, and fixes the commission rate from the tier: a `STANDARD` tier writes 1,000 basis points (ten percent of commissionable premium), and a `PREFERRED` tier writes 1,250 basis points (twelve and a half percent). The producer's `version` increments by one.

Once appointed, a producer is governed by a single status-action operation taking an `action` and an optional `reason` — the reason must be a non-empty string when it is supplied, and it is recorded nowhere on the producer record. An `action` of `SUSPEND` requires `APPOINTED` and moves the agreement `APPOINTED → SUSPENDED`; while suspended the agent may neither create nor submit applications, and no policy may be bound on an application of theirs, but existing policies are left completely untouched and `ytd_commission_cents` does not move. An `action` of `REINSTATE` requires `SUSPENDED` and moves it back `SUSPENDED → APPOINTED`, retaining the `commission_rate_bps` written at agreement execution rather than recomputing it — the suspend-and-reinstate loop may repeat any number of times. An `action` of `TERMINATE` is accepted from either `APPOINTED` or `SUSPENDED` and moves the agreement to the terminal `TERMINATED`. Every one of these actions increments the producer's `version` by one, and any action attempted from a state outside the accepted set is rejected with `ERR_PRODUCER_STATUS_INVALID`. Administrators, any producer and underwriters may read a producer record — this read is not ownership-gated either — and it exposes the running `ytd_commission_cents`.

### 3.2. Rate Filings and Regulatory Approval

A `RateAnalyst` files a plan rate against one territory and one package. The filing names its `cat_zone_id`, a `peril_package` of either `BASIC_FIRE_EO` or `EXTENDED_WIND`, the plan's own `filed_rate_per_1000_cents` (a positive integer count of cents charged per one thousand dollars of dwelling limit), the surveyed `voluntary_market_avg_rate_per_1000_cents` (likewise positive), the `effective_date` on which the rate would take effect, and the `expected_zone_version` described in §2.9. The filing is created in `status` `FILED`, its `filed_by_user_id` is taken from `X-User-ID`, its `reviewed_by_user_id` and `review_note` are null, and the territory's `version` increments by one because a new filing changes the territory's rate posture.

At filing time the server computes `differential_pct`: the filed rate minus the surveyed voluntary average, divided by that same surveyed voluntary average, rounded half up to four decimal places. Because the plan is a market of last resort and may not undercut private carriers, this differential must be **at least** 0.1000 — that is, the filed rate must be at least one tenth above the surveyed average. A differential of exactly 0.1000 is admissible; anything below it is rejected with `ERR_RATE_BELOW_VOLUNTARY_FLOOR`.

Approval sits with the department of insurance. A `Regulator` reviews a filing by supplying a `decision` of either `APPROVE` or `DISAPPROVE` together with an optional `note`, which is stored as `review_note`; the reviewer's `X-User-ID` is stored as `reviewed_by_user_id`. Review is only possible while the filing's `status` is `FILED`, and the reviewer must be a different person from the filer (§2.8). Approval carries one further temporal gate: filings on the same territory-and-package pair must be separated by a **thirty-day quiet buffer**, so the filing being approved must have an `effective_date` no earlier than the `effective_date` of the incumbent already-`APPROVED` filing on that pair — the one with the greatest `effective_date`, a tie on identical `effective_date` broken in favour of the earliest `created_at` — plus thirty days. An `effective_date` that lands anywhere inside that buffer — including exactly the twenty-ninth day after the incumbent's effective date — collides and is rejected with `ERR_FILING_WINDOW_CONFLICT`.

The two decisions diverge sharply in what they touch. `FILED → APPROVED` writes the reviewer fields and increments the filing's `version` by one; it then transitions the previously `APPROVED` filing on the same territory-and-package pair, if one exists, from `APPROVED` to the terminal `SUPERSEDED` (that supersede applies when the newly approved filing has a strictly later `effective_date`, and increments the superseded filing's `version` by one); and finally it increments the territory's `version` by one, because the territory's rate posture has changed. `FILED → DISAPPROVED` also writes the reviewer fields and increments the filing's `version` by one, but supersedes nothing and — this is the asymmetry to watch — does **not** increment the territory's `version`. A supersede never disturbs money already written: policies already bound keep the `rate_filing_id` they pinned and their `annual_premium_cents` unchanged. `DISAPPROVED` and `SUPERSEDED` are both terminal.

Every downstream operation that needs a rate selects it the same way. The server looks for filings whose `status` is `APPROVED`, whose `cat_zone_id` matches the property's territory, whose `peril_package` matches the package in question, and whose `effective_date` falls on or before the reference date for that operation; among those it takes the one with the greatest `effective_date`, breaking a tie on identical `effective_date` in favour of the earliest `created_at`. If no filing satisfies that search, the operation is rejected with `ERR_NO_APPROVED_RATE`. Analysts, regulators, underwriters and administrators may read an individual filing, including its `differential_pct`.

### 3.3. Assembling an Application: Named Insured, Risk and Documented Declinations

Application assembly is producer work, and it begins with two standalone records. The **named insured** is created with a `full_name`, an `email` unique across all applicants, and an optional `phone` that defaults to null. The identifier returned for that record matters beyond bookkeeping: it is the `X-User-ID` with which the `Policyholder` role later authenticates to elect on a take-out offer. The **property** is created inside a territory, naming its `cat_zone_id`, its `address_line`, its `zip_code`, a `construction_type` of `FRAME`, `MASONRY` or `MOBILE`, a `roof_age_years` count of whole years that must be zero or greater, a `replacement_cost_cents` greater than zero, a producer-reported `condition_score` between 0 and 100 inclusive, and an `occupancy` of `OWNER_OCCUPIED`, `TENANT_OCCUPIED` or `VACANT`.

Opening the application itself references the risk and the insured through a payload containing the `property_id` and the `applicant_id`, together with the Coverage A limit sought as `requested_dwelling_limit_cents` (which must be greater than zero) and a `requested_peril_package` of either `BASIC_FIRE_EO` or `EXTENDED_WIND`. The application's `producer_id` is never accepted in the request body — it is taken from the submitting producer's `X-User-ID`. A fresh application sits in `status` `DRAFT` with `declination_count` at 0; `quoted_annual_premium_cents` and `voluntary_equivalent_premium_cents` at 0; `voluntary_market_comparison_pct` at 0.0; and `quote_rate_filing_id`, `submitted_at`, `eligibility_hold_reason`, `decline_reason`, `eligibility_reviewer_user_id`, `approved_to_bind_at` and `bind_deadline_at` all null.

Three gates apply at that moment. The producer's `agreement_status` must be `APPOINTED`, or the request is rejected with `ERR_PRODUCER_NOT_APPOINTED`; a `Producer` whose `X-User-ID` matches no persisted `Producer` record at all draws that same `ERR_PRODUCER_NOT_APPOINTED` rather than an `ERR_NOT_FOUND` or an ownership failure. The broader `EXTENDED_WIND` package is only offered where the territory's dominant `peril` is `HURRICANE`; requesting it in a wildfire or earthquake territory yields `ERR_PERIL_NOT_OFFERED`. And the requested dwelling limit must be no greater than the plan's statutory ceiling of one and a half million dollars — 150,000,000 cents — **and** no greater than the property's own `replacement_cost_cents`; breaching either bound yields `ERR_COVERAGE_LIMIT_EXCEEDED`.

Eligibility for a residual market rests on proof of rejection, and that proof is assembled one **declination record** at a time. Each declination names the `member_insurer_id` of the voluntary carrier that turned the risk down, the `declined_on` date on which it did so, a `reason_code` drawn from `CAT_EXPOSURE`, `CONDITION`, `LOSS_HISTORY`, `NON_RENEWAL` and `APPETITE`, and an `evidence_reference` locating the written declination, which must be a non-empty string. Its `application_id` comes from the application being documented, and only the producer who owns that application may record it. At creation the server computes `verified`: it is true when the named carrier's membership `status` is `ACTIVE` at that moment **and** the `evidence_reference` is non-empty, and false otherwise. Declinations sourced from a carrier already in `RUNOFF` or `WITHDRAWN` are therefore permanently unverified, and only verified rows ever count toward eligibility. At most one declination may exist for a given application-and-carrier pair; a second attempt is rejected with `ERR_DUPLICATE_DECLINATION`. Because a declination is fixed evidence, it carries neither `updated_at` nor `version` (§2.4).

Producers, underwriters and administrators may page the declinations recorded on an application. Underwriters and administrators may page applications generally, narrowing by `applicant_id`, `property_id`, `producer_id`, the pinned `quote_rate_filing_id`, or application `status`.

### 3.4. Submission, Eligibility Routing and Underwriting Review

**Declination sufficiency** is the plan's central eligibility test, and it is evaluated against a moving window rather than against the whole history of an application. The anchor date is the calendar date of the application's `submitted_at`, which is re-written on every successful submission. The window opens sixty days before that anchor date and closes on the anchor date itself, and **both** bounds are inclusive. A declination qualifies when it belongs to this application, when its `verified` flag is true, and when the calendar date in its `declined_on` falls inside that inclusive sixty-day window. Qualifying rows are then collapsed by carrier, so that at most one row per `member_insurer_id` counts: where a single carrier has several qualifying rows, the row with the latest `declined_on` is the one that counts, and a tie on identical `declined_on` is broken in favour of the earliest `created_at`. The resulting `declination_count` is the number of distinct carriers surviving that collapse, and eligibility requires it to be **at least three**.

Submitting an application is the producer's act, permitted only on an application they own whose `status` is `DRAFT` or `ELIGIBILITY_HELD` — anything else is rejected with `ERR_APPLICATION_NOT_SUBMITTABLE`. The producer's agreement must be `APPOINTED`, and an approved rate must exist for the property's territory and the requested package with an `effective_date` on or before the current clock date, selected by the rule in §3.2. Whatever the outcome, a successful submission writes `submitted_at` to the current logical clock, writes `declination_count` from the sufficiency test just described, pins `quote_rate_filing_id` to the filing that rate selection chose, writes the three quote fields, and increments the application's `version` by one.

The routing then forks on the count alone, and **no error is raised on either branch**. A count of three or more routes `DRAFT → SUBMITTED`, leaving `eligibility_hold_reason` null. A count below three routes `DRAFT → ELIGIBILITY_HELD` and writes `eligibility_hold_reason` to the literal string `INSUFFICIENT_DECLINATIONS`. The two branches are otherwise identical: the quote fields are computed and pinned on the held branch exactly as they are on the submitted branch, so an application sitting on hold still shows the plan's price. A held application may be re-submitted once more carriers have declined; when a re-submission from `ELIGIBILITY_HELD` finds a count of three or more it moves `ELIGIBILITY_HELD → SUBMITTED`, re-anchors `submitted_at` to the current clock — which slides the whole sixty-day window forward with it — clears `eligibility_hold_reason` back to null, recomputes `declination_count` and all three quote fields, re-pins `quote_rate_filing_id`, and increments `version`. A re-submission that still finds fewer than three raises no error either: the application simply stays in `ELIGIBILITY_HELD` with `eligibility_hold_reason` rewritten to `INSUFFICIENT_DECLINATIONS`, and its anchor, count, quote fields and `version` move exactly as they do on the successful branch.

The three quote fields are the plan's premium-comparison disclosure. `quoted_annual_premium_cents` is the plan's own price for the risk, computed under the `PROVISIONAL_QUOTE` variant of the annual-premium ladder set out in §3.6: it rates on the producer-reported `condition_score`, carries no improvement credit at all, and uses the submission clock date as the rate reference date. `voluntary_equivalent_premium_cents` is the `VOLUNTARY_EQUIVALENT` variant — the identical ladder with identical inputs, except that the rate substituted into the first step is the pinned filing's `voluntary_market_avg_rate_per_1000_cents` in place of its `filed_rate_per_1000_cents`. `voluntary_market_comparison_pct` is then the quoted plan premium minus the voluntary-equivalent premium, divided by that voluntary-equivalent premium, rounded half up to four decimal places.

An `Underwriter` then reviews eligibility on an application whose `status` is `SUBMITTED` or `ELIGIBILITY_HELD`; from any other state the review is rejected with `ERR_APPLICATION_NOT_REVIEWABLE`. The review carries a `decision` of `ADVANCE` or `DECLINE` plus an optional `decline_reason`. Both decisions record the reviewing underwriter's `X-User-ID` as `eligibility_reviewer_user_id` and increment the application's `version` by one — and that recorded identifier is what later bars the same person from binding the policy.

`ADVANCE` re-runs the sufficiency test, and this is where the variants matter: at review time the anchor date is the **unchanged** `submitted_at`, so declinations that were inside the window at submission can age out of it while the file waits on an underwriter's desk. If the recomputed count is below three the advance is refused with `ERR_INSUFFICIENT_DECLINATIONS` — a hard error, not a routing decision. Otherwise the application moves to `INSPECTION_PENDING`. `DECLINE` moves the application to the terminal `DECLINED` from either `SUBMITTED` or `ELIGIBILITY_HELD`, writing `decline_reason` from the request.

### 3.5. Property Inspection and Condition-Based Remediation

An `Underwriter` orders a site inspection on an application whose `status` is `INSPECTION_PENDING` or `IMPROVEMENTS_REQUIRED`; from any other state the order is refused with `ERR_INSPECTION_NOT_ORDERABLE`. The order may carry an optional `scheduled_for` site-visit date, which is purely informational. The new inspection is created with `ordered_at` set to the current logical clock, `result` `PENDING`, `open_requirement_count` and `cleared_major_count` at 0, and `inspector_user_id`, `completed_at`, `scheduled_for` (when omitted) and `observed_condition_score` null. Ordering a **re-inspection** from `IMPROVEMENTS_REQUIRED` additionally moves the application `IMPROVEMENTS_REQUIRED → INSPECTION_PENDING` and increments its `version` by one; requirements raised by the earlier inspection are not disturbed and keep their own status. Because the reverse move exists too, `IMPROVEMENTS_REQUIRED → INSPECTION_PENDING → IMPROVEMENTS_REQUIRED` is a genuine cycle that may repeat as often as the risk demands.

Completion belongs to the `Inspector`, and it is the sharpest fork in the plan. The completing request carries the `observed_condition_score` the inspector measured, a `result`, and an optional `requirements` array whose entries each name a `code` and a `severity`. Whether the `requirements` array agrees with the `result` is settled earlier, as a schema rule: a `PASS` that carries any requirement entry, and a `PASS_WITH_CONDITIONS` that carries none, are both rejected with `ERR_INVALID_REQUEST` (HTTP 400) before the inspection identifier is even resolved. The inspection's current `result` must then be `PENDING`, or the request is refused with `ERR_INSPECTION_ALREADY_COMPLETED`. All three outcomes write `inspector_user_id` from `X-User-ID`, write `completed_at` to the current logical clock, and write `observed_condition_score`, and all three increment both the inspection's `version` and the application's `version` by one. Beyond that they diverge completely:

- `PENDING → PASS` is available when the request supplies no requirements. It cascades the application `INSPECTION_PENDING → APPROVED_TO_BIND`, writing `approved_to_bind_at` to the current logical clock and `bind_deadline_at` to thirty days after that instant.
- `PENDING → PASS_WITH_CONDITIONS` is available when the request supplies at least one requirement. It creates one improvement requirement per supplied entry, each in `status` `OPEN` with `due_at` set to forty-five days after the inspection's `completed_at`; it writes the inspection's `open_requirement_count` to the number of requirements created and its `cleared_major_count` to 0; and it cascades the application `INSPECTION_PENDING → IMPROVEMENTS_REQUIRED`, on which branch `approved_to_bind_at` and `bind_deadline_at` both remain null.
- `PENDING → FAIL` creates **no** improvement requirements even if the request supplies some, and cascades the application `INSPECTION_PENDING → DECLINED`, writing `decline_reason` to the literal string `INSPECTION_FAILED`.

`PASS`, `PASS_WITH_CONDITIONS` and `FAIL` are all terminal results for an inspection. Each fork writes the parent application's status unconditionally, without first checking that the application is still in `INSPECTION_PENDING`, so where two inspections were ordered while the application sat in `INSPECTION_PENDING`, completing the second one overwrites whatever status the first one produced.

An **improvement requirement** is a prescribed piece of remediation. Its `inspection_id` identifies the inspection that raised it; its `code` is one of `ROOF_REPLACEMENT`, `ELECTRICAL_UPDATE`, `DEFENSIBLE_SPACE` or `VACANCY_CURE`; and its `severity` is either `MAJOR` or `MINOR`. Severity is consequential in two directions: a `MAJOR` requirement earns rating credit when it is genuinely remediated and can never be waived, while a `MINOR` requirement may be waived but earns no credit. The requirement's `due_at` is the informational deadline shown to the producer, and its lifecycle `status` runs `OPEN`, then either `EVIDENCE_SUBMITTED` and on to the terminal `CLEARED`, or directly to the terminal `WAIVED`. Its `evidence_reference`, `cleared_at` and `waiver_reason` are null until the corresponding step writes them.

Two counters on the parent inspection are maintained continuously and must be read carefully. `open_requirement_count` is the number of child requirements whose `status` is `OPEN` **or** `EVIDENCE_SUBMITTED` — submitting evidence does not reduce it, because unverified evidence is not remediation. `cleared_major_count` is the number of child requirements whose `severity` is `MAJOR` and whose `status` is `CLEARED`, and it is the input to the improvement credit in the premium ladder.

The producer who owns the application submits remediation evidence, supplying an `evidence_reference`; the requirement's `status` must be `OPEN`, moving it `OPEN → EVIDENCE_SUBMITTED`, and the parent inspection's `open_requirement_count` is deliberately left unchanged. The requirement's `version` increments by one.

An `Inspector` then clears a remediated requirement, optionally attaching a `note` — which must be a string when supplied and is persisted nowhere on the requirement. Clearance is available only from `EVIDENCE_SUBMITTED`. It writes `cleared_at` to the current logical clock and increments the requirement's `version`; then, on a second hop, it decrements the parent inspection's `open_requirement_count` by one and — only when the requirement's `severity` is `MAJOR` — increments the parent's `cleared_major_count` by one, incrementing the inspection's `version`; then, on a third hop, if `open_requirement_count` has reached zero, the inspection's `result` flips `PASS_WITH_CONDITIONS → PASS` and the application cascades `IMPROVEMENTS_REQUIRED → APPROVED_TO_BIND` with `approved_to_bind_at` set to the current logical clock and `bind_deadline_at` set thirty days later.

An `Underwriter` may instead waive a requirement, supplying a `reason` — mandatory, and a non-empty string — that is stored as `waiver_reason`. Waiver is accepted from either `OPEN` or `EVIDENCE_SUBMITTED`, the requirement's `severity` must be `MINOR` — a `MAJOR` requirement must be physically remediated and a waiver attempt on one is refused with `ERR_MAJOR_REQUIREMENT_NOT_WAIVABLE` — and the waiving underwriter must not be the inspector who raised it (§2.8). Waiver writes `waiver_reason` and `cleared_at` and increments the requirement's `version`; on the second hop it decrements the parent inspection's `open_requirement_count` by one but pointedly does **not** touch `cleared_major_count`, since a waiver earns no improvement credit; and on the third hop, when the open count reaches zero, the same terminal cascade to `PASS` and `APPROVED_TO_BIND` fires exactly as it does on clearance. Evidence submission, clearance and waiver attempted from a status outside their respective accepted sets are all refused with `ERR_REQUIREMENT_STATE_INVALID`.

Underwriters, inspectors, producers and administrators may read an inspection — including its two counters — page the inspections ordered on an application (narrowable by `result`), and page the requirements raised by an inspection (narrowable by requirement `status`).

### 3.6. Binding: Eligibility Gates, the Annual Premium Ladder and Producer Commission

Binding is the `Underwriter`'s act of turning an approved application into a plan policy, and it is the most heavily gated operation in the system. The request names the `application_id` being bound and the `effective_date` on which coverage should begin. The application's `status` must be `APPROVED_TO_BIND`, or the bind is refused with `ERR_APPLICATION_NOT_BINDABLE`.

Several gates key off a single chosen inspection, and which inspection that is must not be guessed: it is the application's **most recently completed** inspection, meaning the one with the greatest `completed_at`, with a tie on identical `completed_at` broken in favour of the earliest `created_at`. That inspection supplies the rating condition score, the vacancy cure evidence and the staleness test.

The gates, in the precedence established by §2.11, are these. The binding underwriter's `X-User-ID` must differ from the application's `eligibility_reviewer_user_id`, or the bind is refused with `ERR_SEGREGATION_OF_DUTIES`. The property's territory must not be `CLOSED`, or `ERR_ZONE_CLOSED`. Where the territory is `RESTRICTED`, the plan writes only hardened risks: the property's `construction_type` must be `MASONRY` **and** the rating condition score — the chosen inspection's `observed_condition_score` at bind — must be at least the territory's `restricted_min_condition_score`; failing either condition yields `ERR_ZONE_RESTRICTED_INELIGIBLE`. The producer named on the application must still be `APPOINTED`, or `ERR_PRODUCER_NOT_APPOINTED`. An approved filing must exist for the property's territory and the application's package with an `effective_date` on or before the bind clock date, or `ERR_NO_APPROVED_RATE`. A property whose `occupancy` is `VACANT` is ineligible unless the chosen inspection carries a `VACANCY_CURE` requirement whose `status` is `CLEARED`; otherwise `ERR_VACANT_PROPERTY_INELIGIBLE`. The chosen inspection's `completed_at` must not precede the bind clock date by more than ninety whole days — the ninetieth day is still fresh, and the test is one-sided, so a `completed_at` falling on or after the bind clock date is never stale — or `ERR_INSPECTION_STALE`. The bind clock instant must be at or before the application's `bind_deadline_at`, or `ERR_BIND_DEADLINE_PASSED`. The new half-open term must not intersect the term of any policy on the same `property_id` whose `coverage_status` is `BOUND` or `IN_FORCE` — touching endpoints, where the new `effective_date` equals an existing `expiration_date`, do not collide — or `ERR_POLICY_TERM_OVERLAP`. Finally, the territory must have headroom: its `aggregate_insured_value_cents` plus this policy's `exposure_value_cents` must be no greater than its `exposure_cap_cents`, or `ERR_ZONE_EXPOSURE_CAP_EXCEEDED`.

A policy that clears all of that is created with a great deal copied and derived. Its `application_id` comes from the request; its `property_id`, `applicant_id` and `producer_id` are copied from the application; its `rate_filing_id` is pinned to the filing that rate selection chose; its `predecessor_policy_id` is null on an original bind; its `dwelling_limit_cents` equals the application's `requested_dwelling_limit_cents`; its `peril_package` is copied from the application's `requested_peril_package`; its `condition_score_at_bind` snapshots the chosen inspection's `observed_condition_score` for later renewal rating; its `exposure_value_cents` equals its `dwelling_limit_cents`; its `commission_returned_cents`, `unearned_premium_cents`, `cancellation_fee_cents` and `refund_cents` all start at 0; and its `cancel_reason` and `cancellation_date` start null. The `effective_date` comes from the request and the `expiration_date` is set to three hundred sixty-five days after it, marking the exclusive end of the term. The `depopulation_status` starts at `NOT_OFFERED`. The `coverage_status` starts at `IN_FORCE` when the `effective_date` is on or before the bind clock date, and at `BOUND` when the policy is future-dated.

Because the plan's packages are narrower than a homeowners form, each policy records exactly what it does **not** cover in `excluded_perils`. A `BASIC_FIRE_EO` policy excludes `WINDSTORM`, `HAIL`, `WATER_DAMAGE`, `THEFT` and `LIABILITY`. An `EXTENDED_WIND` policy — which buys back wind and hail — excludes `WATER_DAMAGE`, `THEFT` and `LIABILITY`.

**The annual premium ladder.** Premium is computed in a pinned sequence of steps, and each monetary step is rounded half up to whole cents before the next step consumes it.

1. **Select the rate.** Take the applicable approved filing by the selection rule of §3.2 and read its `filed_rate_per_1000_cents`. That rate is quoted per one thousand dollars of dwelling limit.
2. **Base premium.** Express the dwelling limit in thousands of dollars by dividing `dwelling_limit_cents` by 100,000, keeping the fractional part. Multiply the selected rate by that figure, then by the construction factor for the property's `construction_type` (1.25 for `FRAME`, 1.00 for `MASONRY`, 1.60 for `MOBILE`), then by the occupancy factor for its `occupancy` (1.00 for `OWNER_OCCUPIED`, 1.15 for `TENANT_OCCUPIED`, 1.45 for `VACANT`), then by the package factor for the `peril_package` (1.00 for `BASIC_FIRE_EO`, 1.35 for `EXTENDED_WIND`). Round the product half up to whole cents; that is `base_premium_cents`.
3. **Catastrophe concentration surcharge.** Read the territory's `concentration_ratio` **before** this policy's own exposure is added to the territory. Subtract 0.60 from it; if the result is negative, treat it as zero. Multiply what remains by 0.45. If that product exceeds 0.25, use 0.25 instead — the surcharge is capped at a quarter of the base premium. Multiply `base_premium_cents` by the resulting surcharge percentage and round half up to whole cents; that is `cat_surcharge_cents`.
4. **Pre-credit premium.** Add `base_premium_cents` and `cat_surcharge_cents`. Both of the next two adjustments are keyed on **this** pre-credit figure and never on a running total, which is what makes the otherwise circular-looking dependency between them well defined.
5. **Condition adjustment.** From the rating condition score, choose a signed adjustment percentage: a reduction of ten percent when the score is at least 85; a reduction of five percent when the score is at least 70 but below 85; no adjustment at all when the score is at least 50 but below 70; and a surcharge of fifteen percent when the score is below 50. Multiply the pre-credit premium by that signed percentage and round half up to whole cents, keeping the sign.
6. **Improvement credit.** Multiply four percent by the chosen inspection's `cleared_major_count`; if the result exceeds eight percent, use eight percent instead — so clearing two or more major requirements reaches the cap. Multiply the pre-credit premium by that credit percentage and round half up to whole cents.
7. **Floor.** Take the pre-credit premium, add the signed condition adjustment, and subtract the improvement credit. If the result is below 35,000 cents — three hundred fifty dollars, the plan's minimum annual premium — use 35,000 cents instead. The outcome is `annual_premium_cents`.

Four variants use that same ladder with different inputs. `PROVISIONAL_QUOTE`, written to an application's `quoted_annual_premium_cents` at submission, rates on the property's producer-reported `condition_score`, treats the cleared-major count as zero so no improvement credit can exist, and uses the submission clock date as the rate reference date. `VOLUNTARY_EQUIVALENT`, written to `voluntary_equivalent_premium_cents` at submission, is identical to `PROVISIONAL_QUOTE` except that step 1 reads the pinned filing's `voluntary_market_avg_rate_per_1000_cents` instead of its filed rate. `BOUND_FINAL`, written to a policy's `annual_premium_cents` at bind, rates on the chosen inspection's `observed_condition_score` — which may differ from the producer-reported figure and therefore move the condition tier — applies the improvement credit from that inspection's `cleared_major_count`, and uses the bind clock date as the rate reference date. `RENEWAL_FINAL`, written to the successor policy on a renewal, rates on the predecessor's `condition_score_at_bind`, treats the cleared-major count as zero because improvement credits do not persist across terms, and uses the renewal's `effective_date` as the rate reference date. In every variant the intermediate legs are persisted on the policy as `base_premium_cents` and `cat_surcharge_cents`.

**Producer commission.** The catastrophe concentration surcharge is never commissionable, so commissionable premium is the policy's `annual_premium_cents` less its `cat_surcharge_cents`. Multiply that by the producer's `commission_rate_bps`, divide by 10,000, and round half up to whole cents; the result is written to the policy's `commission_credited_cents`. On early termination the same unearned fraction used by the refund calculation is applied to the amount originally credited: multiply the policy's `commission_credited_cents` by that unearned fraction, round half up to whole cents, and write the result to `commission_returned_cents`. A producer's `ytd_commission_cents` is a conserved quantity recomputed after every credit and every return: it is the sum, over **all** policies whose `producer_id` is that producer, of `commission_credited_cents` minus `commission_returned_cents`. Cancelled and taken-out policies stay in that sum with their returned amounts, which is exactly what keeps the identity exact.

Binding therefore mutates four records. The new policy is created; the producer's `ytd_commission_cents` rises by the commission credited and the producer's `version` increments; the territory's `aggregate_insured_value_cents` rises by the policy's `exposure_value_cents`, its `concentration_ratio` is recomputed, its `status` is re-derived and its `version` increments by one; and the application moves `APPROVED_TO_BIND → BOUND` with its `version` incremented by one. Underwriters, administrators, policyholders, producers and member-carrier operators may read a policy, which exposes both state dimensions and all premium legs. Underwriters, administrators and member-carrier operators may page policies, narrowing by `application_id`, `property_id`, `applicant_id`, `producer_id`, `rate_filing_id`, the self-referential `predecessor_policy_id`, `coverage_status` or `depopulation_status`.

### 3.7. Term Maintenance: Renewal, Cancellation, Expiry and the Nightly Sweep

Renewing an in-force policy creates a **successor** rather than extending the incumbent. The renewal request carries the successor's `effective_date` and, optionally, a revised `requested_dwelling_limit_cents`; when that is omitted the successor's `dwelling_limit_cents` carries the predecessor's limit forward. The predecessor's `coverage_status` must be `IN_FORCE`, or the renewal is refused with `ERR_POLICY_NOT_IN_FORCE`. The successor is then gated exactly as a bind is on territory posture, producer appointment, rate availability, coverage limit, term overlap and territory headroom: the territory must not be `CLOSED`; where it is `RESTRICTED` the construction must be `MASONRY` and the rating condition score — for a renewal, the predecessor's `condition_score_at_bind` — must be at least `restricted_min_condition_score`; the producer must be `APPOINTED`; an approved filing must cover the territory and package with an `effective_date` on or before the renewal's `effective_date`; the limit must not exceed either 150,000,000 cents or the property's `replacement_cost_cents`; the successor's half-open term must not intersect any `BOUND` or `IN_FORCE` term on the same property; and the territory must have headroom under its `exposure_cap_cents`. The successor is created with `predecessor_policy_id` pointing at the policy being renewed, its `application_id`, `property_id`, `applicant_id`, `producer_id` and `peril_package` copied straight off the predecessor (so both terms answer to the same application record), its `excluded_perils` re-derived from that package, its `condition_score_at_bind` carried forward from the predecessor, its premium computed under the `RENEWAL_FINAL` variant, its exposure added to the territory with the concentration ratio recomputed and the status re-derived, and producer commission credited on the successor. The predecessor is left untouched by the renewal itself, and so is the shared application record: neither its status nor its `version` moves.

Cancellation ends coverage early. An `Underwriter` cancels an `IN_FORCE` policy, and either an `Underwriter` or a `PlanAdmin` may act on the cancellation surface; a policy still merely `BOUND` may be cancelled only when the supplied `cancel_reason` is `PLAN_INITIATED`. The request supplies that `cancel_reason` — `POLICYHOLDER_REQUEST` or `PLAN_INITIATED` — and a `cancel_date`, which is written to the policy's `cancellation_date`. `TAKEOUT_ELECTION` is a server-only reason written solely by the take-out election cascade; a client that supplies it is rejected with `ERR_INVALID_REQUEST`. Cancelling from a coverage state outside the accepted set is refused with `ERR_POLICY_NOT_IN_FORCE`.

**The refund calculation** runs as follows. Count the whole days from the policy's `effective_date` to its `cancellation_date`; that is the days in force. Subtract that count from three hundred sixty-five, treat a negative result as zero, and divide by three hundred sixty-five; that quotient is the unearned fraction, and it equals one when the cancellation date is the effective date itself. Under the `PRO_RATA` variant — which applies when `cancel_reason` is `PLAN_INITIATED` or `TAKEOUT_ELECTION` — the policy's `annual_premium_cents` is multiplied by the unearned fraction and rounded half up to whole cents to give `unearned_premium_cents`. Under the `SHORT_RATE` variant — which applies when `cancel_reason` is `POLICYHOLDER_REQUEST` — the same product is additionally multiplied by 0.90 before rounding, so a policyholder-requested cancellation yields a smaller unearned premium and may therefore also fall into a lower fee tier. The unearned **fraction** itself is the same in both variants; only the money differs.

The fee is then chosen from `unearned_premium_cents` — never from the refund it is subtracted from. It is zero when `cancel_reason` is `TAKEOUT_ELECTION`; zero when the unearned premium is zero; twenty-five dollars (2,500 cents) when the unearned premium is no more than five hundred dollars (50,000 cents); fifty dollars (5,000 cents) when the unearned premium is no more than two thousand dollars (200,000 cents); and otherwise three percent of the unearned premium, rounded half up to whole cents. `refund_cents` is the unearned premium minus that fee, floored at zero.

A cancellation therefore writes `cancel_reason`, `cancellation_date`, `unearned_premium_cents`, `cancellation_fee_cents` and `refund_cents`; writes `commission_returned_cents` and decrements the producer's `ytd_commission_cents` by the same amount; then, on a second hop, releases the policy's `exposure_value_cents` from the territory's `aggregate_insured_value_cents` and recomputes `concentration_ratio`; then, on a third hop, re-derives the territory's `status` from the fallen ratio — walking back down from `CLOSED` through `RESTRICTED` to `OPEN` as headroom returns — and increments the territory's `version` by one. The policy's own `version` increments by one. `CANCELLED`, `EXPIRED` and `TAKEN_OUT` are all terminal coverage states.

**The nightly sweep** is an administrator-only batch capability that advances every time-driven transition in the plan at once and reports four counters: `activated_policy_count`, `expired_policy_count`, `expired_offer_count` and `withdrawn_application_count`. It performs four jobs, in the order given and all inside the one request, so a future-dated policy whose term has already run out by the clock date is activated by the first job and then expired by the second within the same sweep, counting once in each of the two counters. First, any policy whose `coverage_status` is `BOUND` and whose `effective_date` is on or before the clock date moves `BOUND → IN_FORCE`; the territory's `aggregate_insured_value_cents` does **not** change on this move, because a `BOUND` policy was already counted in the exposure, and only the policy's `version` increments. Second, any policy whose `coverage_status` is `IN_FORCE` and whose `expiration_date` is on or before the clock date moves `IN_FORCE → EXPIRED`, releasing its `exposure_value_cents` from the territory, recomputing the concentration ratio, re-deriving the territory's `status` and incrementing the territory's `version` — but generating no refund and no commission return at all, because the full term was earned. Third, any take-out offer whose `status` is `OUTSTANDING` and whose `election_deadline_at` is strictly before the clock instant moves `OUTSTANDING → EXPIRED`, resets the underlying policy's `depopulation_status` from `OFFER_OUTSTANDING` back to `NOT_OFFERED`, and leaves the offering carrier's `takeout_credit_count` unchanged. Fourth, any application whose `status` is `APPROVED_TO_BIND` and whose `bind_deadline_at` is strictly before the clock instant moves `APPROVED_TO_BIND → WITHDRAWN` with `eligibility_hold_reason` written to the literal string `BIND_WINDOW_LAPSED`. `BOUND`, `DECLINED` and `WITHDRAWN` are the terminal application states.

Setting the logical clock is likewise an administrator-only test-driving capability: it accepts a `to_iso8601` instant, moves the clock to it, and reports the resulting `current_utc` (see §2.6).

### 3.8. Depopulation: Take-Out Offers and Policyholder Election

Depopulation is how a residual market shrinks. An operator acting for an `ACTIVE` member carrier offers to assume one of the plan's in-force policies, and the policyholder — never the plan, never the carrier — decides.

Making an offer requires the target policy's `coverage_status` to be `IN_FORCE` (otherwise `ERR_POLICY_NOT_IN_FORCE`) and its `depopulation_status` to be `NOT_OFFERED` (otherwise `ERR_OFFER_ALREADY_OUTSTANDING`), and the offering carrier's membership `status` to be `ACTIVE` — a carrier in `RUNOFF` or `WITHDRAWN` may not offer, and is refused with `ERR_MEMBER_NOT_ACTIVE`. The request names the `member_insurer_id` of the offering carrier, which must equal the caller's `X-User-ID`; the `offered_premium_cents`, which must be greater than zero; a `comparable_coverage_flag` attesting that the carrier's coverage is at least as broad as the plan package, which is a required boolean — omitting it or sending a non-boolean is a schema violation (`ERR_INVALID_REQUEST`), whereas sending `false` is a comparability failure; and an `election_deadline_at`, the last instant at which the policyholder may elect, inclusive. For the offer to be a genuine alternative rather than a price trap, `comparable_coverage_flag` must be true **and** `offered_premium_cents` must be no greater than the plan's `annual_premium_cents` multiplied by 1.15 and rounded half up to whole cents; either failure is refused with `ERR_OFFER_NOT_COMPARABLE`.

The offer is created in `status` `OUTSTANDING` with `elected_at`, `withdrawal_reason` null and `credit_units_granted` at 0, and the policy's second state dimension moves `NOT_OFFERED → OFFER_OUTSTANDING` with the policy's `version` incremented by one. The coverage dimension is completely untouched by this move — `depopulation_status` and `coverage_status` are independent dimensions carried on the same policy record.

Election belongs to the `Policyholder` whose `X-User-ID` matches the `applicant_id` of the policy behind the offer. The offer's `status` must be `OUTSTANDING`, or the election is refused with `ERR_OFFER_NOT_OUTSTANDING`, and the election clock instant must be at or before `election_deadline_at`, inclusive of that instant, or `ERR_ELECTION_WINDOW_CLOSED`. The request carries a single `election` field valued either `ACCEPT` or `DECLINE`, and the two branches have deliberately disjoint side-effect sets.

`ACCEPT` moves the offer `OUTSTANDING → ACCEPTED`, writing `elected_at` to the current logical clock and `credit_units_granted` to 1, and incrementing the offer's `version`. On the next hop the offering carrier's `takeout_credit_count` rises by the granted credit units and the carrier's `version` increments by one — this is how a carrier earns the depopulation credits it can later offset against an assessment. On the coverage branch of the same request the policy moves `IN_FORCE → TAKEN_OUT` and `OFFER_OUTSTANDING → ELECTED_TAKEOUT`, with `cancel_reason` written to `TAKEOUT_ELECTION`, `cancellation_date` written to the current clock date, `unearned_premium_cents` computed under the `PRO_RATA` variant, `cancellation_fee_cents` forced to 0 and `refund_cents` therefore equal to the full unearned premium. Commission is clawed back: `commission_returned_cents` is written and the producer's `ytd_commission_cents` decrements by the same amount. On a third hop the territory's `aggregate_insured_value_cents` drops by the policy's `exposure_value_cents` and its `concentration_ratio` is recomputed; on a fourth hop its `status` is re-derived from the new ratio and its `version` increments by one. The policy's own `version` increments by one.

`DECLINE` moves the offer `OUTSTANDING → DECLINED`, writing `elected_at` and `credit_units_granted` of 0 and incrementing the offer's `version`, and moves only the policy's depopulation dimension `OFFER_OUTSTANDING → ELECTED_RETAIN` with the policy's `version` incremented by one. Nothing else moves at all: the `coverage_status` stays `IN_FORCE`, no refund is computed, no commission is clawed back, the territory's exposure and status are not recomputed, and the carrier's `takeout_credit_count` is **not** incremented.

The offering carrier may instead withdraw an outstanding offer, supplying a `reason` — mandatory, and a non-empty string — that is stored as `withdrawal_reason`; the withdrawing operator's `X-User-ID` must equal the offer's `member_insurer_id`. Withdrawal moves the offer `OUTSTANDING → WITHDRAWN`, increments its `version`, and resets the policy's `depopulation_status` from `OFFER_OUTSTANDING` back to `NOT_OFFERED` with the policy's `version` incremented by one — which makes the policy offerable again by any `ACTIVE` member, so the depopulation dimension is genuinely cyclic. `ACCEPTED`, `DECLINED`, `WITHDRAWN` and `EXPIRED` are all terminal offer states.

Member-carrier operators, policyholders, administrators and underwriters may read an individual offer; administrators, underwriters and member-carrier operators may page offers, narrowing by `policy_id`, `member_insurer_id` or offer `status`.

### 3.9. Member Assessments When Losses Exceed Plan Reserves

When a catastrophe drives incurred losses past what the plan holds in reserve, the shortfall is assessed back onto the member carriers. A `PlanAdmin` opens an **assessment event** naming the `cat_zone_id` whose losses triggered it, the `trigger_loss_cents` incurred (which must be zero or greater), the `reserve_balance_cents_at_trigger` available when the loss was booked (likewise zero or greater), and an `allocation_basis` of either `MARKET_SHARE` or `PREMIUM_VOLUME`. The server immediately writes `assessable_amount_cents` as the trigger loss minus the reserve balance, with a negative result replaced by zero. The event opens in `status` `DRAFT` with `allocated_total_cents` and `remainder_cents` at 0, `allocation_run_count` at 0 and `cancellation_reason` null.

Running the allocation is also administrator work, and it is the operation protected by `expected_assessment_event_version` (§2.9). It is accepted from `status` `DRAFT` or `ALLOCATED`; from anything else the refusal is `ERR_ASSESSMENT_STATE_INVALID`. Two fiscal gates follow: `assessable_amount_cents` must be **strictly greater than zero**, so a loss exactly equal to the reserve balance yields zero and blocks the run with `ERR_LOSSES_WITHIN_RESERVES`; and the eligible member set must be non-empty with a total basis weight greater than zero, or `ERR_NO_ASSESSABLE_MEMBERS`.

**The allocation waterfall** runs as follows, and its rounding order is pinned. The eligible members are those whose membership `status` is `ACTIVE` or `RUNOFF`; `WITHDRAWN` carriers are excluded. Each eligible member's weight is its `market_share_pct` when the event's `allocation_basis` is `MARKET_SHARE`, and its `written_premium_share_pct` when the basis is `PREMIUM_VOLUME`; that weight is snapshotted onto the resulting allocation as `basis_weight_pct`. The total weight is the sum of those weights across the eligible set. Each member's raw share is `assessable_amount_cents` multiplied by that member's weight and divided by the total weight. **Each member's raw share is rounded half up to whole cents first**, and only then is the residue reconciled — summing raw shares and rounding once at the end is explicitly not the rule. The reconciliation figure, `remainder_cents`, is `assessable_amount_cents` minus the sum of the per-member rounded shares, and it may be negative. It is absorbed entirely by one member: the eligible member with the greatest weight, with a tie on equal weight broken in favour of the earliest `created_at` among those members. That absorber's rounded share, plus the remainder, is its `gross_share_cents`; every other member's `gross_share_cents` is simply its rounded share.

Depopulation credits then offset each member's bill. A credit unit is worth five thousand dollars — 500,000 cents — and a member holds `takeout_credit_count` of them. The offset written to `takeout_credit_applied_cents` is the smaller of two figures: fifty percent of that member's `gross_share_cents`, rounded half up to whole cents, and the member's `takeout_credit_count` multiplied by 500,000 cents. `net_due_cents` is `gross_share_cents` minus `takeout_credit_applied_cents`. The number of whole credits actually spent, `credits_consumed`, is `takeout_credit_applied_cents` divided by 500,000 and rounded **down** to a whole number; those credits are not deducted from the member yet — that happens only when the event settles.

The two bases are not interchangeable. Under `MARKET_SHARE` a carrier with a small statewide share but a large premium book is assessed less than it would be under `PREMIUM_VOLUME` for the identical event, and because the absorber is chosen by weight, both the per-member shares **and** the identity of the remainder absorber can differ between the two bases on the same event.

A first run moves the event `DRAFT → ALLOCATED`: it creates one allocation per eligible member, each in `status` `PENDING` with `paid_at` null, writes `allocated_total_cents` and `remainder_cents`, increments `allocation_run_count` by one, raises each touched member's `cumulative_assessed_cents` by that member's `net_due_cents` while incrementing each member's `version` by one, and increments the event's `version` by one. A re-run is a legitimate supersede and moves the event `ALLOCATED → ALLOCATED`: every prior allocation on the event whose `status` is `PENDING` moves `PENDING → ABATED`, a fresh allocation set is built from the members' **current** weights (so a carrier that moved to `WITHDRAWN` between runs drops out and the total weight changes), `allocation_run_count` increments again, each member's `cumulative_assessed_cents` is recomputed from non-abated allocations only, and the event's `version` increments by one. A member's `cumulative_assessed_cents` is always the sum of `net_due_cents` over that member's allocations whose `status` is `PENDING` or `PAID`, and an event's `allocated_total_cents` is the sum of `gross_share_cents` over its allocations whose `status` is not `ABATED` — a figure that must equal `assessable_amount_cents` for as long as the event sits in `ALLOCATED`, `INVOICED` or `SETTLED`. Whenever an allocation moves `PENDING → ABATED`, the owning member's `cumulative_assessed_cents` falls by that allocation's `net_due_cents` and the allocation's `version` increments by one.

Invoicing moves the event `ALLOCATED → INVOICED`, which requires `allocated_total_cents` to equal `assessable_amount_cents` — a mismatch is refused with `ERR_ASSESSMENT_STATE_INVALID`, the same code the wrong starting status draws — makes the allocations payable, and increments the event's `version` by one.

Settlement is carrier work. A member-carrier operator pays its own allocation, supplying `amount_cents`. The allocation's `status` must be `PENDING` and its parent event's `status` must be `INVOICED`, or the payment is refused with `ERR_ALLOCATION_NOT_PAYABLE`; the allocation's `member_insurer_id` must equal the caller's `X-User-ID`; the paying carrier's membership `status` must be `ACTIVE` or `RUNOFF` — a `WITHDRAWN` carrier may not pay, and is refused with `ERR_MEMBER_NOT_ACTIVE`; and `amount_cents` must equal the allocation's `net_due_cents` exactly, since the plan accepts no partial or over-payment, or the refusal is `ERR_PAYMENT_AMOUNT_MISMATCH`. A successful payment moves the allocation `PENDING → PAID`, writes `paid_at` to the current logical clock and increments the allocation's `version` by one. On a second hop, if no allocation on the event remains in `PENDING`, the event moves `INVOICED → SETTLED` and its `version` increments by one. On a third hop, triggered by that settlement, **every** allocation on the event has its `credits_consumed` deducted from its own member's `takeout_credit_count`, with each such member's `version` incremented by one — this is the moment the depopulation credits earned back in §3.8 are actually spent.

An administrator may cancel an assessment from `DRAFT`, `ALLOCATED` or `INVOICED`, supplying a `reason` — mandatory, and a non-empty string — that is stored as `cancellation_reason`. From `DRAFT` the cancellation simply writes the reason and increments the event's `version`. From `ALLOCATED` it additionally moves every allocation whose `status` is `PENDING` to `ABATED`, decreases each affected member's `cumulative_assessed_cents` by that allocation's `net_due_cents` — restoring the pre-event value — increments each affected member's `version` by one, and writes `allocated_total_cents` back to 0 alongside the reason. From `INVOICED` the pending allocations are abated in exactly the same way, while allocations already `PAID` keep their `PAID` status and their `net_due_cents` remains inside the member's `cumulative_assessed_cents`; `allocated_total_cents` is in every case rewritten as the sum of `gross_share_cents` over the allocations that survive the abatement, which is 0 from `DRAFT` or `ALLOCATED` but the paid allocations' total from `INVOICED`. `SETTLED` and `CANCELLED` are the terminal event states, and `PAID` and `ABATED` the terminal allocation states.

Administrators, regulators and member-carrier operators may read an assessment event — including `assessable_amount_cents`, `allocated_total_cents` and `remainder_cents` — and page its allocations, narrowing by allocation `status`; administrators and member-carrier operators may also page the allocations charged to any given carrier — that reverse lookup is role-gated, not ownership-gated — each allocation naming its `assessment_event_id` and `member_insurer_id`.

## 4. Endpoint Definitions

Operations that bring a genuinely new resource into existence — admitting a member carrier, defining a territory, registering a producer, an applicant, a property or a rate filing, opening an application, recording a declination, ordering an inspection, binding a policy, renewing into a successor policy, making a take-out offer, or opening an assessment event — return `201 Created`. Every other operation, including all state transitions on an existing resource, all reads, and the batch and clock capabilities, returns `200 OK`. The complete surface is mounted under `/fair-plan`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fair-plan/_clock/set_current_utc` | Set the logical clock; before the first call it reads exactly `2026-08-01T00:00:00Z` | PlanAdmin |
| POST | `/fair-plan/sweeps/expiration` | Nightly batch: activate future-dated binds, expire terms, expire lapsed offers, withdraw lapsed bind windows | PlanAdmin |
| POST | `/fair-plan/member-insurers` | Admit a voluntary-market carrier as a plan member | PlanAdmin |
| PATCH | `/fair-plan/member-insurers/{id}` | Move a member into run-off or withdrawal, or restate its assessment basis weights | PlanAdmin |
| GET | `/fair-plan/member-insurers/{id}` | Read one member carrier including its credit and assessment counters | PlanAdmin, Regulator, MemberInsurerUser |
| GET | `/fair-plan/member-insurers` | List member carriers | PlanAdmin, Regulator |
| GET | `/fair-plan/member-insurers/{id}/declinations` | Declinations this carrier has issued | PlanAdmin, Regulator, MemberInsurerUser |
| GET | `/fair-plan/member-insurers/{id}/allocations` | Assessment allocations charged to this carrier | PlanAdmin, MemberInsurerUser |
| POST | `/fair-plan/cat-zones` | Define a catastrophe exposure territory with its aggregate cap | PlanAdmin |
| GET | `/fair-plan/cat-zones/{id}` | Read one territory including its derived exposure posture | PlanAdmin, Regulator, Underwriter, RateAnalyst |
| GET | `/fair-plan/cat-zones/{id}/properties` | Properties located in this territory | PlanAdmin, Underwriter |
| GET | `/fair-plan/cat-zones/{id}/rate-filings` | Rate filings for this territory | PlanAdmin, RateAnalyst, Regulator, Underwriter |
| GET | `/fair-plan/cat-zones/{id}/assessment-events` | Assessment events triggered by losses in this territory | PlanAdmin, Regulator |
| POST | `/fair-plan/producers` | Register a licensed producer; the agreement starts unexecuted | PlanAdmin |
| POST | `/fair-plan/producers/{id}/agreement-execution` | Execute the producer agreement, appointing the producer and fixing the commission rate | PlanAdmin |
| POST | `/fair-plan/producers/{id}/status-actions` | Suspend, reinstate or terminate a producer | PlanAdmin |
| GET | `/fair-plan/producers/{id}` | Read one producer including the conserved year-to-date commission | PlanAdmin, Producer, Underwriter |
| POST | `/fair-plan/applicants` | Create the named-insured record a producer will submit for | Producer |
| POST | `/fair-plan/properties` | Register the risk being submitted, inside a catastrophe territory | Producer |
| GET | `/fair-plan/properties/{id}` | Read one property | Producer, Underwriter, Inspector, PlanAdmin |
| POST | `/fair-plan/applications` | Open a plan application in `DRAFT` | Producer |
| GET | `/fair-plan/applications/{id}` | Read one application including its declination count and pinned quote | Producer, Underwriter, Inspector, PlanAdmin |
| GET | `/fair-plan/applications` | List applications | Underwriter, PlanAdmin |
| POST | `/fair-plan/applications/{id}/declinations` | Record a documented voluntary-market declination supporting eligibility | Producer |
| GET | `/fair-plan/applications/{id}/declinations` | Declinations recorded on this application | Producer, Underwriter, PlanAdmin |
| POST | `/fair-plan/applications/{id}/submission` | Submit or re-submit the application; routes on the declination count and pins the quote | Producer |
| POST | `/fair-plan/applications/{id}/eligibility-review` | Advance or decline eligibility | Underwriter |
| POST | `/fair-plan/applications/{id}/inspections` | Order a property inspection or re-inspection | Underwriter |
| GET | `/fair-plan/applications/{id}/inspections` | Inspections ordered on this application | Underwriter, Inspector, Producer, PlanAdmin |
| GET | `/fair-plan/inspections/{id}` | Read one inspection including its requirement counters | Underwriter, Inspector, Producer, PlanAdmin |
| POST | `/fair-plan/inspections/{id}/completion` | Complete the inspection as pass, pass-with-conditions or fail | Inspector |
| GET | `/fair-plan/inspections/{id}/requirements` | Improvement requirements raised by this inspection | Underwriter, Inspector, Producer, PlanAdmin |
| POST | `/fair-plan/improvement-requirements/{id}/evidence` | Submit remediation evidence for a requirement | Producer |
| POST | `/fair-plan/improvement-requirements/{id}/clearance` | Clear a remediated requirement, driving the inspection and application cascade | Inspector |
| POST | `/fair-plan/improvement-requirements/{id}/waiver` | Waive a minor requirement; the raising inspector may not waive it | Underwriter |
| POST | `/fair-plan/rate-filings` | File a plan rate against a territory and package, carrying the zone version last observed | RateAnalyst |
| POST | `/fair-plan/rate-filings/{id}/review` | Approve or disapprove a filing; approval supersedes the prior approved filing | Regulator |
| GET | `/fair-plan/rate-filings/{id}` | Read one rate filing including its differential | RateAnalyst, Regulator, Underwriter, PlanAdmin |
| POST | `/fair-plan/policies` | Bind an approved application into a plan policy | Underwriter |
| GET | `/fair-plan/policies/{id}` | Read one policy including both state dimensions and all premium legs | Underwriter, PlanAdmin, Policyholder, Producer, MemberInsurerUser |
| GET | `/fair-plan/policies` | List policies | Underwriter, PlanAdmin, MemberInsurerUser |
| POST | `/fair-plan/policies/{id}/cancellation` | Cancel coverage mid-term with the short-rate or pro-rata refund variant | Underwriter, PlanAdmin |
| POST | `/fair-plan/policies/{id}/renewal` | Renew an in-force policy into a successor term | Underwriter |
| POST | `/fair-plan/policies/{id}/takeout-offers` | An active member carrier offers to take the policy out of the plan | MemberInsurerUser |
| GET | `/fair-plan/takeout-offers/{id}` | Read one take-out offer | MemberInsurerUser, Policyholder, PlanAdmin, Underwriter |
| GET | `/fair-plan/takeout-offers` | List take-out offers | PlanAdmin, Underwriter, MemberInsurerUser |
| POST | `/fair-plan/takeout-offers/{id}/election` | Accept (depopulate) or decline (retain) the take-out offer | Policyholder |
| POST | `/fair-plan/takeout-offers/{id}/withdrawal` | Withdraw an outstanding offer, freeing the policy for another | MemberInsurerUser |
| POST | `/fair-plan/assessment-events` | Open an assessment event for losses exceeding plan reserves | PlanAdmin |
| POST | `/fair-plan/assessment-events/{id}/allocation-run` | Apportion the assessable amount across eligible members; a re-run supersedes the prior set | PlanAdmin |
| POST | `/fair-plan/assessment-events/{id}/invoicing` | Invoice the allocated assessment, making allocations payable | PlanAdmin |
| POST | `/fair-plan/assessment-events/{id}/cancellation` | Cancel the assessment, abating unpaid allocations and restoring member counters | PlanAdmin |
| GET | `/fair-plan/assessment-events/{id}` | Read one assessment event including its allocation totals | PlanAdmin, Regulator, MemberInsurerUser |
| GET | `/fair-plan/assessment-events/{id}/allocations` | Allocations of this event | PlanAdmin, Regulator, MemberInsurerUser |
| POST | `/fair-plan/assessment-allocations/{id}/payment` | Settle an allocation in full; the last payment settles the event and consumes credits | MemberInsurerUser |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_IDENTIFIER` | 409 |
| `ERR_DUPLICATE_DECLINATION` | 409 |
| `ERR_APPLICATION_NOT_SUBMITTABLE` | 409 |
| `ERR_APPLICATION_NOT_REVIEWABLE` | 409 |
| `ERR_INSPECTION_NOT_ORDERABLE` | 409 |
| `ERR_INSPECTION_ALREADY_COMPLETED` | 409 |
| `ERR_REQUIREMENT_STATE_INVALID` | 409 |
| `ERR_FILING_NOT_REVIEWABLE` | 409 |
| `ERR_APPLICATION_NOT_BINDABLE` | 409 |
| `ERR_POLICY_NOT_IN_FORCE` | 409 |
| `ERR_OFFER_ALREADY_OUTSTANDING` | 409 |
| `ERR_OFFER_NOT_OUTSTANDING` | 409 |
| `ERR_ASSESSMENT_STATE_INVALID` | 409 |
| `ERR_ALLOCATION_NOT_PAYABLE` | 409 |
| `ERR_PRODUCER_STATUS_INVALID` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_MAJOR_REQUIREMENT_NOT_WAIVABLE` | 422 |
| `ERR_ZONE_CLOSED` | 409 |
| `ERR_ZONE_RESTRICTED_INELIGIBLE` | 409 |
| `ERR_PRODUCER_NOT_APPOINTED` | 409 |
| `ERR_MEMBER_NOT_ACTIVE` | 409 |
| `ERR_NO_APPROVED_RATE` | 409 |
| `ERR_INSUFFICIENT_DECLINATIONS` | 422 |
| `ERR_PERIL_NOT_OFFERED` | 422 |
| `ERR_COVERAGE_LIMIT_EXCEEDED` | 422 |
| `ERR_VACANT_PROPERTY_INELIGIBLE` | 422 |
| `ERR_INSPECTION_STALE` | 422 |
| `ERR_BIND_DEADLINE_PASSED` | 422 |
| `ERR_POLICY_TERM_OVERLAP` | 409 |
| `ERR_FILING_WINDOW_CONFLICT` | 409 |
| `ERR_ELECTION_WINDOW_CLOSED` | 422 |
| `ERR_RATE_BELOW_VOLUNTARY_FLOOR` | 422 |
| `ERR_OFFER_NOT_COMPARABLE` | 422 |
| `ERR_ZONE_EXPOSURE_CAP_EXCEEDED` | 422 |
| `ERR_LOSSES_WITHIN_RESERVES` | 422 |
| `ERR_NO_ASSESSABLE_MEMBERS` | 422 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
