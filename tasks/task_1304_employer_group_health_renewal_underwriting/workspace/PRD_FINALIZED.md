# Employer Group Health Renewal Underwriting API — Product Requirements Document

## 1. Introduction

Employer group health renewal is where an insurer's margin discipline meets a broker's book-of-business leverage. Each year, every in-force group comes up for re-pricing: the underwriter must gather a fresh employee census, pull paid-claims experience from the claim system, decide how much that experience is statistically credible against the manual rate book, model alternative benefit plan designs, produce a quote the broker can take to the employer, and then survive a negotiation that may swing the rate several times before acceptance. Along the way the insurer must honor rate-increase caps, respect segregation-of-duties between the underwriter who submits claims data and the senior underwriter who reviews it, price stop-loss coverage for groups that choose level funding, protect rate guarantees against enrollment drift after acceptance, and satisfy commission-disclosure regulation when broker compensation crosses per-enrollee thresholds.

This document specifies the Employer Group Health Renewal Underwriting API, the system of record for that entire workflow. The API is organized around the **Underwriting Case** — a single employer group's renewal file — and the resources that hang beneath it: the census snapshot, the claims experience record, candidate benefit plan designs, one or more successive quotes, stop-loss quotes for level-funded arrangements, a negotiation trail, post-acceptance enrollment change events, and the commission disclosure that closes the file. All resources are mounted under the `/underwriting-cases` API surface, with the broker register living under `/brokers`.

The audience is the engineering team implementing the service. Business rules are expressed narratively in §3; the HTTP contract is summarized in §4; every rejection the API can produce is catalogued in §5.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying a value the server cannot interpret, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

The system recognizes exactly four roles, spelled precisely as follows: `Underwriter`, `SeniorUnderwriter`, `Broker`, and `ComplianceOfficer`. Each endpoint is restricted to a defined role set (enumerated in §4); an authenticated caller whose role is not authorized for the requested operation is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The meaning of `X-User-ID` differs by role:

- When `X-User-Role` is `Broker`, `X-User-ID` is the `id` of the acting `Broker` record. Ownership checks on any resource that references a broker — principally an underwriting case's `broker_id` — compare the resource's foreign-key field to `X-User-ID`. A broker who counters a case whose broker of record is someone else is rejected with `ERR_NOT_BROKER_OF_RECORD` (HTTP 403).
- When `X-User-Role` is `Underwriter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it (for example, as `assigned_underwriter_id` on the underwriting case at creation time, and as the identity of the claims submitter used for the segregation-of-duties check) but does not compare it to any entity's `id` for ownership.
- When `X-User-Role` is `SeniorUnderwriter`, `X-User-ID` is likewise an opaque operator identifier; the server uses it only to enforce the rule that the claims reviewer must differ from the claims submitter (`ERR_SAME_REVIEWER_AS_SUBMITTER`).
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque identifier with read-only reach: the role can view every entity in the system but can perform no mutations.

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

Endpoints that return lists of resources are paginated via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. All list endpoints return resources sorted by `created_at` in ascending order unless stated otherwise. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every resource in the system — underwriting cases, brokers, census snapshots, claims experiences, plan designs, quotes, stop-loss quotes, negotiation rounds, enrollment change events, and commission disclosures — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set once at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 on creation and increments by one on every mutation, including system-driven state transitions and derived-field recomputation.

Any write that changes a resource's state or recomputed fields — including cascades that touch a parent — refreshes the parent's `updated_at` and increments its `version`. This property is load-bearing for the optimistic concurrency rule in §2.5.

### 2.5. Optimistic Concurrency on Quote Creation

Exactly one endpoint in the API participates in optimistic concurrency control: the creation of a quote against an underwriting case. Such a request must carry `expected_case_version`, a non-optional integer holding the `version` of the parent underwriting case as the client last observed it. If the case's current `version` no longer matches `expected_case_version` — for example because another underwriter created a quote in the meantime, which itself advances the case's `version` — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) before any business logic is evaluated. No other endpoint accepts a version field; the check exists solely to prevent quote creation against a case the writer has not recently observed.

### 2.6. Validation Order and Nested Path Resolution

All requests pass through validations in a fixed order of precedence. Header presence and well-formedness are checked first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), followed by role authorization for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`), followed by existence of every resource identifier in the path (`ERR_NOT_FOUND`). Where an OCC version check applies — quote creation only — it runs immediately after existence checks and strictly before any business-rule validation, so a stale `expected_case_version` surfaces as `ERR_STALE_VERSION` rather than being masked by a downstream business error.

For nested paths (for example, a census snapshot addressed beneath a case), identifiers are validated left to right: the system confirms the parent exists before attempting to resolve the child, and the first identifier in the path that does not resolve determines the 404 response. After existence and version checks, business-state guards fire: the parent-case state guard (`ERR_CASE_INVALID_STATE` and its more specific case-state errors), then the entity's own transition guard (`ERR_INVALID_STATE_TRANSITION` and the more specific per-entity "not in state X" errors), then the rule-specific business constraints enumerated throughout §3 — broker-active checks, group-size floors, census arithmetic, claims-period rules, segregation of duties, modeled-plan prerequisites, funding-type floors, round-proposer checks, approval gates, level-funding requirements, and disclosure thresholds.

### 2.7. Monetary Representation and Rounding

All money in the system — premiums, rates, commissions, deductibles, stop-loss amounts — is stored and transmitted as integer cents unless a field is explicitly documented as a decimal fraction (percentages such as `commission_pct`, ratios such as `coinsurance_pct`, and factors such as `credibility_factor`). Final computed cent values are rounded to whole cents using the round-half-up method. Rates and percentages that the scaffold treats as fractional measures — the credibility factor, renewal increase percentage, actuarial value, plan relativity, and enrollment change percentage — are rounded half-up to four decimal places. The IBNR completion factor is a two-decimal exact lookup with no arithmetic rounding of its own. Under no circumstance may an implementation return monetary values as strings.

### 2.8. The Logical Clock and Quote Expiry

Time-dependent behavior — most notably quote expiry against the renewal effective date — is driven by a logical clock rather than wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`. An `Underwriter` may advance it via an admin-style test-driving capability by supplying a `to_iso8601` timestamp; every subsequent time-dependent evaluation in the system uses the logical clock's current reading. Quote expiry (§3.7) is evaluated against this clock whenever time-dependent operations are evaluated.

## 3. Business Logic & Workflows

### 3.1. Opening the File: Cases and Brokers

The renewal file begins in one of two places. An `Underwriter` may register a brokerage partner by supplying the firm's `firm_name`, its `license_number`, the two-letter `state_code` of licensure, and the standard `commission_pct` the firm earns (expressed as a decimal, such as 0.04 for four percent). A newly registered broker is immediately `ACTIVE`; a `SeniorUnderwriter` may later update a broker's `status` — among `ACTIVE`, `SUSPENDED`, and `TERMINATED` — as market-conduct events dictate.

With a broker on file, an `Underwriter` opens an **Underwriting Case** by providing the employer's legal `group_name`, total eligible `group_size` as an integer, the four-digit `sic_code`, the two-letter `state_code` of situs, the renewal `effective_date`, the in-force `current_premium_annual` in cents, the `current_renewal_date`, the `funding_type` (one of `FULLY_INSURED`, `LEVEL_FUNDED`, or `SELF_FUNDED`), and the `broker_id` of the broker of record. The case is born in `INTAKE`, and the server stamps `assigned_underwriter_id` with the creating underwriter's `X-User-ID`. The case's computed pricing fields — `credibility_factor`, `manual_rate_cents`, `experience_rate_cents`, `blended_rate_cents`, `rate_cap_pct`, and the `is_rate_cap_applied` flag — all start at their zero defaults (0, 0, 0, 0, 0, and false respectively) and only take on real values as census and claims data flow through the pipeline. The default rate cap on any renewal is a fifteen percent maximum increase, expressed as the decimal 0.15, and `rate_cap_pct` carries that value once rating computes.

From `INTAKE`, the underwriter submits the case for census collection, which requires two things: the case must still be in `INTAKE` (otherwise `ERR_CASE_NOT_IN_INTAKE`), and the broker of record must be `ACTIVE` (otherwise `ERR_BROKER_NOT_ACTIVE`). Success moves the case to `CENSUS_PENDING`. Either the underwriter or the broker of record may also withdraw a case at nearly any point in its life — from `INTAKE`, `CENSUS_PENDING`, `CENSUS_RECEIVED`, `CLAIMS_PENDING`, `RATING_IN_PROGRESS`, `QUOTED`, or `NEGOTIATING` — moving it to the terminal `WITHDRAWN` state with no further effect; a withdraw attempt from any other state (for example, `APPROVED`, `DECLINED`, or an already-`WITHDRAWN` case) fails with `ERR_INVALID_STATE_TRANSITION`.

### 3.2. Census Intake and the Manual Rate

Once a case is `CENSUS_PENDING`, the underwriter uploads a **Census Snapshot** containing the headcount `total_employees`, the currently enrolled `enrolled_employees`, the covered `dependent_count`, and the `tier_distribution` — an object breaking enrollment into `EE` (employee only), `ES` (employee plus spouse), `EC` (employee plus children), and `EF` (family) buckets. On submission the snapshot is born `PENDING` with its `submitted_at` timestamp recorded, and the server immediately computes two demographic measures from the census file: the weighted `average_age` of enrolled members and the `gender_ratio` of females to total enrolled.

Validation is a separate, deliberate act. An underwriter validating a snapshot runs four checks; the snapshot must be `PENDING` (else `ERR_CENSUS_NOT_PENDING`), its `total_employees` must equal the parent case's `group_size` (else `ERR_CENSUS_COUNT_MISMATCH`), its `enrolled_employees` must be greater than zero (else `ERR_EMPTY_ENROLLMENT`), and the four values inside `tier_distribution` must sum exactly to `enrolled_employees` (else `ERR_TIER_SUM_MISMATCH`). A snapshot that fails review can instead be rejected outright, moving it from `PENDING` to `REJECTED` with no arithmetic checks applied; rejection requires only that the snapshot still be `PENDING`.

When a snapshot passes validation it becomes `VALIDATED`, and the cascade begins: if the parent case was `CENSUS_PENDING`, it advances automatically to `CENSUS_RECEIVED`, and the server computes the two pillars of manual-book pricing against the case.

First, the **manual rate**. The reference manual rate for the book is 45,000 cents PEPM ($450.00 per employee per month). This base is multiplied by three adjustment factors and rounded half-up to whole cents. The age factor keys off the census `average_age`: below 30 the factor is 0.85; at least 30 but below 40 it is 1.00; at least 40 but below 50 it is 1.15; at least 50 but below 60 it is 1.35; at 60 or above it is 1.60. The gender factor keys off `gender_ratio`: below 0.40 the factor is 0.95; from 0.40 through 0.60 inclusive it is 1.00; above 0.60 it is 1.08. The industry factor is read from the first two digits of the case's `sic_code`: 01–09 (agriculture) maps to 0.90, 10–14 (mining) to 1.10, 15–17 (construction) to 1.05, 20–39 (manufacturing) to 1.00, 40–49 (transportation) to 1.02, 50–59 (wholesale and retail) to 0.98, 60–67 (finance) to 0.95, 70–89 (services) to 1.00, 91–97 (public administration) to 0.97, and any other prefix to 1.00. The product `base × age × gender × industry`, rounded half-up to whole cents, lands on the case as `manual_rate_cents`. Note that the census's tier mix (`tier_distribution`, with tier load factors of 1.00 for EE, 2.00 for ES, 1.80 for EC, and 2.90 for EF) is retained on the snapshot for downstream plan modeling even though the manual rate itself is demographic.

Second, the census-only **credibility factor**. Credibility Z is the smaller of two sub-factors, capped at 1.0, and stored rounded half-up to four decimal places. The group-size factor is 0.0 when `group_size` is below 25 (too small for any credibility), the group size divided by 100 when the size is at least 25 but below 100, the group size divided by 500 when the size is at least 100 but below 500, and 1.0 at 500 lives or more. The months factor is 0.0 below 12 months of experience, the month count divided by 24 from 12 up to but not including 24 months, and 1.0 at 24 months or more; at census-validation time no claims experience exists yet, so the months factor contributes nothing and the credibility reflects size alone until claims arrive.

### 3.3. Claims Experience and Credibility Blending

A case in `CENSUS_RECEIVED` becomes eligible for experience rating, but only if it clears the small-group floor: requesting claims data requires the case to be in `CENSUS_RECEIVED` (else `ERR_CASE_NOT_IN_CENSUS_RECEIVED`) and requires `group_size` of at least 25 (else `ERR_GROUP_TOO_SMALL_EXPERIENCE`). Success moves the case to `CLAIMS_PENDING`.

The underwriter then creates a **Claims Experience** record with the `experience_period_start` and `experience_period_end`, the aggregate `total_paid_claims_cents` for the period, the `total_enrollment_months` summed across the period's monthly enrollment counts, the `large_claim_count` of claims breaching the pooling point, and the `pooling_threshold_cents` above which individual claims are capped and pooled away. The record is born `PENDING`.

Submitting the record for review is gated: it must still be `PENDING` (else `ERR_CLAIMS_NOT_PENDING`), the period end must fall strictly after the period start (else `ERR_INVALID_EXPERIENCE_PERIOD`, HTTP 400), and the experience must span at least twelve whole months (else `ERR_INSUFFICIENT_EXPERIENCE_MONTHS`). On successful submission three derived values are computed: `months_of_experience` as the count of whole months between start and end inclusive; `pooled_claims_cents` as the portion of paid claims sitting above the pooling threshold; and `experience_claim_cost_cents` as the net claim cost feeding experience rating, namely `total_paid_claims_cents` with `pooled_claims_cents` removed. The record moves to `SUBMITTED`.

Review is reserved for a `SeniorUnderwriter`, and the desk enforces segregation of duties: the reviewer must not be the same user who submitted the record, or the review is refused with `ERR_SAME_REVIEWER_AS_SUBMITTER` (HTTP 403); the record must also be in `SUBMITTED` (else `ERR_CLAIMS_NOT_SUBMITTED`). A `SeniorUnderwriter` may instead reject the record from either `PENDING` or `SUBMITTED`, moving it to `REJECTED` with no preconditions. A successful review moves the record to `REVIEWED`, computes the `completion_ratio` — the IBNR completion factor, an exact two-decimal lookup by months of experience: 1.00 at 24 months or more, 0.98 from 18 up to but not including 24 months, 0.95 from 12 up to but not including 18 months, and 0.85 below 12 months (a period that short would already have been refused at submission) — and, if the parent case is sitting in `CLAIMS_PENDING`, advances it automatically to `RATING_IN_PROGRESS`. That advance triggers the experience-side rating cascade on the case.

The **experience rate** builds a forward-looking PEPM in five steps. Start from the net claim cost (`experience_claim_cost_cents`, already pooled). Adjust for incurred-but-not-reported claims by dividing that cost by the `completion_ratio`. Trend the result forward by applying the annual medical trend of 6.5 percent twice — two years of trend from the mid-point of the experience period to the mid-point of the renewal period — compounding annually. Convert to a per-employee-per-month figure by dividing by `total_enrollment_months`. Finally gross up for retention — administration, risk, and profit margin set at 15 percent — by dividing by 0.85, which is one minus the retention percentage. The result, rounded half-up to whole cents, becomes the case's `experience_rate_cents`. When a `SeniorUnderwriter` reviewing the file judges the experience thin and the credibility factor is below 0.5, a conservative variant applies: a ten percent margin load multiplies the experience rate by 1.10 before rounding.

With both pillars present the **blended rate** is a credibility-weighted average: the credibility factor times `experience_rate_cents` plus one-minus-the-credibility-factor times `manual_rate_cents`. The blend is then tested against the rate cap: the maximum permissible PEPM is the current in-force PEPM — `current_premium_annual` divided by 12 and then by the census `enrolled_employees` — grown by one plus `rate_cap_pct` (the default 0.15). If the raw blend exceeds that ceiling, the blend is clamped to the ceiling and `is_rate_cap_applied` becomes true; otherwise it becomes false. The final `blended_rate_cents` is rounded half-up to whole cents. A `SeniorUnderwriter` may override the cap, in which case the blend is the raw Z-weighted average with no clamping. The credibility factor itself is re-derived at this point blending census size with claims months as described in §3.2.

### 3.4. Benefit Plan Design and Actuarial Modeling

Plan design work runs in parallel with claims collection. An `Underwriter` drafts a **Benefit Plan Design** on the case by supplying a marketing `plan_name`; the cost-sharing skeleton of `deductible_individual`, `deductible_family`, `oop_max_individual`, and `oop_max_family` (all in cents); the plan-paid `coinsurance_pct` as a decimal; the `copay_primary` and `copay_specialist` in cents; the funding-relevant `employer_contribution_pct` as a decimal between 0 and 1; the `contribution_strategy` (one of `FLAT_DOLLAR`, `PERCENTAGE`, or `TIERED`); and optionally the `is_reference_plan` flag, which defaults to false. The design is born `DRAFT`.

Modeling a design is what makes it quotable. Modeling requires the plan to be `DRAFT` (else `ERR_PLAN_NOT_DRAFT`) and the parent case to have reached `CENSUS_RECEIVED` or any later state (else `ERR_CASE_NOT_READY_FOR_MODELING`). Modeling computes two numbers. The **actuarial value** starts at 1.00 and is whittled down: the individual deductible subtracts 0.02 of AV for every 50,000 cents ($500) of deductible — that is, the deductible in cents divided by 50,000, times 0.02. The whole intermediate value is then multiplied by 0.60 plus 0.40 times the `coinsurance_pct`, so richer plan-paid coinsurance preserves more value. Out-of-pocket exposure above 200,000 cents ($2,000) individual subtracts a further 0.005 of AV per 100,000 cents ($1,000) of excess — the excess measured as the amount by which `oop_max_individual` exceeds 200,000 cents, floored at zero, divided by 100,000, times 0.005. Copays shave value too: the sum of `copay_primary` and `copay_specialist`, divided by 100,000, times 0.01 is subtracted. The result is clamped so it never falls below 0.50 and never exceeds 1.00, then rounded half-up to four decimal places and stored as `actuarial_value`.

The **relativity factor** expresses the plan's price relative to the case's reference plan. A plan whose `is_reference_plan` flag is true always has `relativity_factor` of exactly 1.0 — it is the anchor. For any other plan, the server finds the reference plan on the same case; if none exists, the plan is treated as its own base and also receives 1.0. Otherwise the relativity is this plan's `actuarial_value` divided by the reference plan's `actuarial_value`, rounded half-up to four decimal places. A modeled plan moves to `MODELED`. An underwriter may reject a design from `DRAFT` unconditionally, or from `MODELED` provided no quote in `PROPOSED` or `COUNTERED` status references it — attempting to reject a plan with such live quotes is refused with `ERR_PLAN_HAS_ACTIVE_QUOTES`. When a quote referencing a modeled plan is ultimately accepted, the plan transitions automatically from `MODELED` to `SELECTED`.

### 3.5. Quoting and the Rate Proposal

Quote creation is the one OCC-guarded write in the system (§2.5). To open a quote, an `Underwriter` names the `plan_design_id` being priced, the quote-level `funding_type` (one of `FULLY_INSURED` or `LEVEL_FUNDED` — self-funded administration is priced outside this flow), the `rate_guarantee_months` (12, 18, or 24), the `enrollment_change_threshold` as a decimal such as 0.10, and the `expected_case_version` described earlier. Two business guards apply before the draft is created: at least one plan design on the case must be in `MODELED` status (else `ERR_NO_MODELED_PLAN`), and a `LEVEL_FUNDED` quote additionally requires the case `group_size` to be at least 10 (else `ERR_GROUP_TOO_SMALL_LEVEL_FUNDED`). The quote arrives in `DRAFT` with a server-assigned sequential `quote_number` (1, 2, 3, … within the case), `negotiation_round` initialized to 0, and `parent_quote_id` empty. Creating the quote is itself a mutation of the parent case: the case's `version` increments by one. The case must also be in a quotable posture for the first quote — `RATING_IN_PROGRESS` — or the request fails with `ERR_CASE_NOT_IN_RATING`.

Proposing the quote is where every rate comes to life. The quote must be `DRAFT` (else `ERR_QUOTE_NOT_DRAFT`) and the parent case must be in `RATING_IN_PROGRESS`, `QUOTED`, or `NEGOTIATING` (else `ERR_CASE_NOT_QUOTABLE`). On proposal the quoted PEPM, `pepm_rate_cents`, is the case's `blended_rate_cents` multiplied by the referenced plan's `relativity_factor`, rounded half-up to whole cents. For a `LEVEL_FUNDED` quote that PEPM decomposes into three components that must sum back exactly to the whole: `claims_fund_cents` at 82 percent of the rate, `admin_fee_cents` at 12 percent, and `stop_loss_premium_cents` at 6 percent; for a `FULLY_INSURED` quote these components do not apply. The `annual_premium_cents` is the PEPM times 12 times the validated census `enrolled_employees`. The `renewal_increase_pct` measures the movement against the in-force premium: the annual premium minus `current_premium_annual`, divided by `current_premium_annual`, rounded half-up to four decimal places (the current PEPM baseline being `current_premium_annual` divided by 12 divided by `enrolled_employees`). The `broker_commission_cents` is the annual premium multiplied by the broker of record's `commission_pct`, rounded half-up to whole cents; dividing that commission by `enrolled_employees` yields the per-enrollee figure, and when the per-enrollee commission reaches or exceeds 5,000 cents — the $50-per-enrollee-per-year disclosure threshold — `commission_disclosure_required` is set true. The quote moves to `PROPOSED`, and if the parent case was in `RATING_IN_PROGRESS`, it advances automatically to `QUOTED`.

### 3.6. Negotiation: Counters, Responses, and Acceptance

The negotiation dance is a strict alternation between broker and underwriter, tracked as first-class records. When a quote sits in `PROPOSED`, the broker of record may counter it — the broker must be `ACTIVE` (else `ERR_BROKER_NOT_ACTIVE`), must be the case's broker of record (else `ERR_NOT_BROKER_OF_RECORD`), and the quote must indeed be `PROPOSED` (else `ERR_QUOTE_NOT_PROPOSED`). A counter carries `proposed_pepm_cents`, a `proposed_contribution_pct`, and a free-text `justification` of at least 20 characters, and may optionally include a `proposed_deductible_individual` when the broker wants plan-design changes on the table. The counter moves the quote from `PROPOSED` to `COUNTERED`, spawns a **Negotiation Round** record — numbered sequentially within the quote via `round_number` starting at 1, stamped `proposed_by` with `BROKER`, carrying the proposed figures and the quote's `quote_id` and grandparent `case_id` — and swings the parent case from `QUOTED` to `NEGOTIATING`.

The underwriter answers with a response of the same shape — `proposed_pepm_cents`, `proposed_contribution_pct`, optional `proposed_deductible_individual`, and `justification` — which requires the quote to be `COUNTERED` (else `ERR_QUOTE_NOT_COUNTERED`) and the case to be `NEGOTIATING` (else `ERR_CASE_NOT_NEGOTIATING`). The response moves the quote back from `COUNTERED` to `PROPOSED`, spawns the underwriter's `UNDERWRITER`-attributed negotiation round on the same quote, and returns the parent case from `NEGOTIATING` to `QUOTED`. In this way the case oscillates `QUOTED → NEGOTIATING → QUOTED` while the parties trade rounds, and the quote's `negotiation_round` reflects the depth of the exchange.

Either party may abandon a round it proposed: withdrawing a round requires the round to be `PROPOSED` (else `ERR_ROUND_NOT_PROPOSED`) and requires the caller to be the party recorded in `proposed_by` — only the proposer may withdraw (else `ERR_NOT_ROUND_PROPOSER`, HTTP 403) — moving the round to `WITHDRAWN`. Rounds also resolve automatically with their parent quote: when the quote is accepted, its outstanding rounds move to `ACCEPTED`; when the quote is rejected or superseded, they move to `REJECTED`.

Acceptance is the broker's move and the case's climax. Accepting a quote requires the quote to be `PROPOSED` (else `ERR_QUOTE_NOT_PROPOSED`) and the broker to be `ACTIVE` (else `ERR_BROKER_NOT_ACTIVE`); it is permitted whether the case sits in `QUOTED` or in `NEGOTIATING`. The acceptance cascade is wide: the quote becomes `ACCEPTED`; the referenced plan design becomes `SELECTED`; every other non-terminal quote on the case becomes `SUPERSEDED`; any negotiation rounds still open on those quotes resolve to `REJECTED`; the parent case moves to `APPROVED`; and a **Commission Disclosure** is minted against the case, the accepted quote, and the broker of record. The disclosure computes `total_commission_cents` (the accepted quote's annual broker commission), the effective `commission_pct`, the `per_enrollee_cents` figure, and compares the total against the system-held `disclosure_threshold_cents` — $50 per enrollee per year, i.e. 5,000 cents per enrollee — setting `requires_disclosure` true when the per-enrollee commission meets or exceeds that threshold. The disclosure is born `PENDING` with `disclosed_at` unset.

Quotes can die in several other ways. Either the broker or the underwriter may reject a live quote — from `PROPOSED` or from `COUNTERED` (a quote in any other state is refused with `ERR_QUOTE_NOT_PROPOSED`) — moving it to `REJECTED`. The underwriter (or a senior) may decline the entire case while it is `QUOTED` or `NEGOTIATING` (else `ERR_CASE_NOT_DECLINABLE`), moving the case to terminal `DECLINED`. And time kills quotes too: any quote still sitting in `PROPOSED` or `COUNTERED` once the logical clock passes thirty days before the case's `effective_date` expires automatically to `EXPIRED`.

### 3.7. Stop-Loss Pricing for Level-Funded Business

Level-funded groups buy stop-loss protection against catastrophic claims, priced as a child of the quote. An `Underwriter` creates a **Stop-Loss Quote** under a quote by supplying the `specific_deductible_cents` — the per-claimant annual attachment — and the `aggregate_attachment_pct` as a decimal of expected claims (1.25 for a 125 percent corridor), and optionally `laser_claimant_ids` naming individual claimants who will carry elevated `laser_deductible_cents`. The record is born `DRAFT`, stamped with both its parent `quote_id` and grandparent `case_id`.

Pricing the stop-loss requires the record to be `DRAFT` (else `ERR_STOP_LOSS_NOT_DRAFT`), the parent quote to be live in `PROPOSED` or `COUNTERED` (else `ERR_QUOTE_NOT_ACTIVE`), and the parent quote's funding type to be `LEVEL_FUNDED` (else `ERR_NOT_LEVEL_FUNDED`). The computation proceeds in five parts. Expected annual claims, `expected_annual_claims_cents`, project the case's experience rate across the year: `experience_rate_cents` times 12 times the census `enrolled_employees` times 0.82, the claims-fund share of the level-funded dollar; when no experience rate exists the manual rate stands in. The aggregate attachment, `aggregate_attachment_cents`, is expected annual claims multiplied by `aggregate_attachment_pct`, rounded half-up to whole cents. The specific premium is tiered by the specific deductible: at or below 2,500,000 cents ($25,000) the rate is 850 per thousand per hundred enrollees; above that and at or below 5,000,000 cents it is 620; above that and at or below 10,000,000 cents it is 410; above 10,000,000 cents it is 280. The specific premium formula takes the deductible in thousands, multiplies by the applicable per-thousand rate, multiplies by `enrolled_employees`, and divides by 100, rounding half-up to whole cents into `specific_premium_cents`. The aggregate premium, `aggregate_premium_cents`, is a flat 2 percent of the aggregate attachment, rounded half-up to whole cents. The `total_stop_loss_premium_cents` is the sum of the two. When `laser_claimant_ids` is non-empty, the specific premium is loaded an additional 25 percent — multiplied by 1.25 and re-rounded to whole cents — and the total recomputed as the loaded specific premium plus the aggregate premium. The record moves to `QUOTED`.

Binding is the final stop-loss act: the record must be `QUOTED` (else `ERR_STOP_LOSS_NOT_QUOTED`) and the parent quote must have reached `ACCEPTED` (else `ERR_QUOTE_NOT_ACCEPTED`), at which point the stop-loss becomes `BOUND`. The underwriter may instead decline a quoted stop-loss, moving it from `QUOTED` to `DECLINED` (again requiring `QUOTED`, else `ERR_STOP_LOSS_NOT_QUOTED`).

### 3.8. Post-Acceptance: Enrollment Changes and Rate Guarantees

A rate guarantee is only as strong as the census it was priced on. After a case is `APPROVED`, either the underwriter or the broker may report an **Enrollment Change Event** naming the impacted `quote_id`, an `event_type` of `NEW_HIRE`, `TERMINATION`, `COBRA_ELECTION`, or `PLAN_MIGRATION`, the signed `change_count` (positive to add enrollees, negative to remove), and the `effective_date` of the change. The event is born `REPORTED`.

Processing is the underwriter's job and is gated twice: the event must be `REPORTED` (else `ERR_ENROLLMENT_NOT_REPORTED`) and the parent case must be `APPROVED` (else `ERR_CASE_NOT_APPROVED`). Processing computes the `revised_enrollment` as the census `enrolled_employees` plus the event's `change_count`, and the `enrollment_change_pct` as `change_count` divided by `enrolled_employees`, rounded half-up to four decimal places. The outcome then forks on the magnitude of the swing. When the absolute value of `enrollment_change_pct` is at most the quote's `enrollment_change_threshold`, the guarantee holds: the event becomes `PROCESSED`, `guarantee_voided` is false, and `rate_adjustment_factor` is exactly 1.0. When the absolute change exceeds the threshold, the guarantee is voided: `guarantee_voided` is set true, the event becomes `VOIDED_GUARANTEE`, and the rate adjusts upward by 2 percent for every 5 percent of excess swing beyond the threshold — the excess measured as the absolute change percentage minus the threshold, divided into 0.05 bands rounded up to a whole band count, each band adding 0.02 to a base factor of 1.0. The parent quote's rate is then multiplied by this `rate_adjustment_factor`, repricing the guarantee-breached group.

### 3.9. Commission Disclosure and Acknowledgment

The disclosure minted at acceptance (§3.6) has its own small lifecycle. While it sits `PENDING`, an underwriter may formally disclose it to the group — but only when disclosure is actually required: if `requires_disclosure` is false, the disclose attempt is refused with `ERR_DISCLOSURE_NOT_REQUIRED`, and if the disclosure is not `PENDING` the attempt fails with `ERR_DISCLOSURE_NOT_PENDING`. Successful disclosure moves the record to `DISCLOSED` and stamps `disclosed_at` with the current timestamp. The broker of record then acknowledges receipt, moving the disclosure from `DISCLOSED` (else `ERR_DISCLOSURE_NOT_DISCLOSED`) to the terminal `ACKNOWLEDGED` state, closing the renewal file's compliance trail.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Request and response bodies follow the envelope of §2.2; readers should reconstruct each endpoint's payload from the §3 narrative for its workflow.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/underwriting-cases` | Create a new underwriting case | Underwriter |
| GET | `/underwriting-cases` | List underwriting cases (filters: `status`, `funding_type`, `broker_id`) | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| GET | `/underwriting-cases/{caseId}` | Get a specific underwriting case | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| POST | `/underwriting-cases/{caseId}/submit-for-census` | Submit case for census collection | Underwriter |
| POST | `/underwriting-cases/{caseId}/request-claims` | Request claims experience data | Underwriter |
| POST | `/underwriting-cases/{caseId}/decline` | Decline the underwriting case | Underwriter, SeniorUnderwriter |
| POST | `/underwriting-cases/{caseId}/withdraw` | Withdraw the underwriting case | Underwriter, Broker |
| POST | `/brokers` | Register a broker | Underwriter |
| GET | `/brokers` | List brokers (filter: `status`) | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| GET | `/brokers/{brokerId}` | Get a specific broker | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| PUT | `/brokers/{brokerId}` | Update broker status | SeniorUnderwriter |
| POST | `/underwriting-cases/{caseId}/census-snapshots` | Submit a census snapshot | Underwriter |
| GET | `/underwriting-cases/{caseId}/census-snapshots` | List census snapshots for a case | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| GET | `/census-snapshots/{censusId}` | Get a specific census snapshot | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| POST | `/census-snapshots/{censusId}/validate` | Validate a census snapshot | Underwriter |
| POST | `/census-snapshots/{censusId}/reject` | Reject a census snapshot | Underwriter |
| POST | `/underwriting-cases/{caseId}/claims-experiences` | Create a claims experience record | Underwriter |
| GET | `/underwriting-cases/{caseId}/claims-experiences` | List claims experiences for a case | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| GET | `/claims-experiences/{claimsId}` | Get a specific claims experience | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| POST | `/claims-experiences/{claimsId}/submit` | Submit claims for review | Underwriter |
| POST | `/claims-experiences/{claimsId}/review` | Review submitted claims | SeniorUnderwriter |
| POST | `/claims-experiences/{claimsId}/reject` | Reject claims experience | SeniorUnderwriter |
| POST | `/underwriting-cases/{caseId}/plan-designs` | Create a benefit plan design | Underwriter |
| GET | `/underwriting-cases/{caseId}/plan-designs` | List plan designs for a case | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| GET | `/plan-designs/{planId}` | Get a specific plan design | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| POST | `/plan-designs/{planId}/model` | Model a plan design (compute AV and relativity) | Underwriter |
| POST | `/plan-designs/{planId}/reject` | Reject a plan design | Underwriter |
| POST | `/underwriting-cases/{caseId}/quotes` | Create a quote for a plan design | Underwriter |
| GET | `/underwriting-cases/{caseId}/quotes` | List quotes for a case | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| GET | `/quotes/{quoteId}` | Get a specific quote | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| POST | `/quotes/{quoteId}/propose` | Propose a quote (compute all rates) | Underwriter |
| POST | `/quotes/{quoteId}/counter` | Broker counters a proposed quote | Broker |
| POST | `/quotes/{quoteId}/respond` | Underwriter responds to counter-proposal | Underwriter |
| POST | `/quotes/{quoteId}/accept` | Accept a proposed quote | Broker |
| POST | `/quotes/{quoteId}/reject-quote` | Reject a proposed or countered quote | Broker, Underwriter |
| POST | `/quotes/{quoteId}/stop-loss-quotes` | Create a stop-loss quote for a level-funded quote | Underwriter |
| GET | `/quotes/{quoteId}/stop-loss-quotes` | List stop-loss quotes for a quote | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| GET | `/stop-loss-quotes/{slqId}` | Get a specific stop-loss quote | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| POST | `/stop-loss-quotes/{slqId}/quote` | Quote a stop-loss (compute premiums) | Underwriter |
| POST | `/stop-loss-quotes/{slqId}/bind` | Bind a stop-loss quote | Underwriter |
| POST | `/stop-loss-quotes/{slqId}/decline-slq` | Decline a stop-loss quote | Underwriter |
| GET | `/quotes/{quoteId}/negotiation-rounds` | List negotiation rounds for a quote | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| GET | `/negotiation-rounds/{roundId}` | Get a specific negotiation round | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| POST | `/negotiation-rounds/{roundId}/withdraw-round` | Withdraw a negotiation round | Underwriter, Broker |
| POST | `/underwriting-cases/{caseId}/enrollment-changes` | Report an enrollment change event | Underwriter, Broker |
| GET | `/underwriting-cases/{caseId}/enrollment-changes` | List enrollment change events for a case | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| GET | `/enrollment-changes/{eventId}` | Get a specific enrollment change event | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| POST | `/enrollment-changes/{eventId}/process` | Process an enrollment change event | Underwriter |
| GET | `/underwriting-cases/{caseId}/commission-disclosures` | List commission disclosures for a case | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| GET | `/commission-disclosures/{discId}` | Get a specific commission disclosure | Underwriter, SeniorUnderwriter, Broker, ComplianceOfficer |
| POST | `/commission-disclosures/{discId}/disclose` | Provide commission disclosure to group | Underwriter |
| POST | `/commission-disclosures/{discId}/acknowledge` | Acknowledge receipt of commission disclosure | Broker |
| POST | `/_clock/set_current_utc` | Set the logical clock | Underwriter |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CASE_INVALID_STATE` | 409 |
| `ERR_CASE_NOT_IN_INTAKE` | 409 |
| `ERR_CASE_NOT_IN_CENSUS_RECEIVED` | 409 |
| `ERR_CASE_NOT_IN_RATING` | 409 |
| `ERR_CASE_NOT_NEGOTIATING` | 409 |
| `ERR_CASE_NOT_QUOTABLE` | 409 |
| `ERR_CASE_NOT_DECLINABLE` | 409 |
| `ERR_CASE_NOT_APPROVED` | 409 |
| `ERR_CASE_NOT_READY_FOR_MODELING` | 409 |
| `ERR_BROKER_NOT_ACTIVE` | 409 |
| `ERR_NOT_BROKER_OF_RECORD` | 403 |
| `ERR_CENSUS_NOT_PENDING` | 409 |
| `ERR_CENSUS_COUNT_MISMATCH` | 409 |
| `ERR_EMPTY_ENROLLMENT` | 409 |
| `ERR_TIER_SUM_MISMATCH` | 409 |
| `ERR_CLAIMS_NOT_PENDING` | 409 |
| `ERR_CLAIMS_NOT_SUBMITTED` | 409 |
| `ERR_INVALID_EXPERIENCE_PERIOD` | 400 |
| `ERR_INSUFFICIENT_EXPERIENCE_MONTHS` | 409 |
| `ERR_SAME_REVIEWER_AS_SUBMITTER` | 403 |
| `ERR_PLAN_NOT_DRAFT` | 409 |
| `ERR_PLAN_HAS_ACTIVE_QUOTES` | 409 |
| `ERR_NO_MODELED_PLAN` | 409 |
| `ERR_QUOTE_NOT_DRAFT` | 409 |
| `ERR_QUOTE_NOT_PROPOSED` | 409 |
| `ERR_QUOTE_NOT_COUNTERED` | 409 |
| `ERR_QUOTE_NOT_ACTIVE` | 409 |
| `ERR_QUOTE_NOT_ACCEPTED` | 409 |
| `ERR_GROUP_TOO_SMALL_EXPERIENCE` | 409 |
| `ERR_GROUP_TOO_SMALL_LEVEL_FUNDED` | 409 |
| `ERR_STOP_LOSS_NOT_DRAFT` | 409 |
| `ERR_STOP_LOSS_NOT_QUOTED` | 409 |
| `ERR_NOT_LEVEL_FUNDED` | 409 |
| `ERR_ROUND_NOT_PROPOSED` | 409 |
| `ERR_NOT_ROUND_PROPOSER` | 403 |
| `ERR_ENROLLMENT_NOT_REPORTED` | 409 |
| `ERR_DISCLOSURE_NOT_PENDING` | 409 |
| `ERR_DISCLOSURE_NOT_DISCLOSED` | 409 |
| `ERR_DISCLOSURE_NOT_REQUIRED` | 409 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
