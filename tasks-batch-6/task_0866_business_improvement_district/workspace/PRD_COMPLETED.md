# Business Improvement District API — Product Requirements Document

## 1. Introduction

A Business Improvement District (BID) is a self-governed geographic area in which commercial property owners agree to a supplemental annual assessment that funds enhanced clean, safe, and marketing services beyond what the municipality provides. This API is the system of record for the entire lifecycle of such a district: enrolling member parcels, weighting each parcel's share of the levy, adopting an annual budget and work plan, certifying assessments onto the county tax bill, collecting cash (including delinquency penalties and daily interest), delivering field services through ambassadors, resolving owner disputes, and periodically renewing the district's authorization through a weighted property-owner petition.

The domain is deliberately adversarial in three ways. First, money must reconcile exactly — a certified levy is the per-parcel-rounded sum of every certified assessment, and a downward dispute adjustment must ripple back through the collection account and the fiscal-year ledger without leaking a cent. Second, authority is split across parties who must not be able to act unilaterally: the staff who prepare a budget cannot adopt it, and the board member who verifies a renewal petition cannot cast its approving vote. Third, several quantities are computed twice — once provisionally and once for the record — against a parcel population that may shift between the two moments. The specification below fixes every rate, rounding rule, ordering, and precondition precisely so that two independent implementations converge on the same cents and the same rejection codes.

This document defines the resource model, the global request/response contract, the business workflows, the complete endpoint surface, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. If either header is absent, or if `X-User-Role` is not one of the five roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The five roles are:

- **`DistrictAdministrator`** — BID management staff. Registers districts, parcels, fiscal years, budgets and work-plan lines; proposes and reverts budgets; adjudicates disputes (review, request information, resolve); opens and submits renewal petitions; manages ambassadors and shifts; assigns, closes and cancels service requests. A `DistrictAdministrator` may **not** adopt a budget and may **not** verify or vote on a petition — those are reserved to the board as a segregation-of-duties boundary.
- **`BoardMember`** — the governing board. Activates a forming district, adopts proposed budgets, verifies and votes on renewal petitions, and reads financial reports. A `BoardMember` may **not** prepare or propose budgets and may **not** resolve disputes.
- **`TaxCollector`** — the county tax office. Posts assessment payments, marks accounts delinquent, and writes off uncollectible accounts.
- **`PropertyOwner`** — a parcel owner acting on behalf of their own parcel. Files, answers, and withdraws disputes; signs petitions; pays their own assessment; and logs service requests.
- **`Ambassador`** — a field ambassador acting on behalf of their own record. Starts and resolves the service requests assigned to them.

Two roles are **entity-backed**, and their `X-User-ID` is a foreign key into a persisted entity. When `X-User-Role` is `PropertyOwner`, `X-User-ID` is the `id` of the acting `Parcel`; ownership checks on any resource that traces back to a parcel — a payment on a collection account, a dispute transition of the RESPOND or WITHDRAW kind, a petition signature, or a service-request the owner logged — compare the resource's owning parcel to `X-User-ID`. When `X-User-Role` is `Ambassador`, `X-User-ID` is the `id` of the acting `Ambassador`; starting or resolving a service request compares the request's `assigned_ambassador_id` to `X-User-ID`. A mismatch between an entity-backed principal and the resource it is trying to act on yields `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The other three roles are **opaque**. When `X-User-Role` is `DistrictAdministrator`, `BoardMember`, or `TaxCollector`, `X-User-ID` is an operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. It is, however, recorded where a transition captures it — most importantly, the `BoardMember` who verifies a petition has their `X-User-ID` stored as `verified_by_user_id`, which the subsequent vote consults for the four-eyes rule.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1 and a maximum of 100; a supplied value outside that band is a malformed request. `offset` defaults to 0 and has a minimum of 0. Every collection is returned sorted by `created_at` in ascending order (oldest first). The `meta` block of a list response reports `limit`, `offset`, `total_count` (the total number of matching records before the page window is applied), and `has_more` (true when records remain beyond the current window).

### 2.4. Common Resource Properties and Identifiers

Every resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format) and an integer `version` that begins at 1 on creation and increments by one on every persisted mutation of that resource.

Two entities are append-only ledger events and therefore carry **only** `id` and `created_at` — they have neither `updated_at` nor `version`: a `Payment` (an immutable record of one cash application) and a `PetitionSignature` (an immutable record of one parcel's position on a petition). All other entities — districts, parcels, fiscal years, budgets, work-plan lines, assessments, collection accounts, disputes, renewal petitions, ambassadors, ambassador shifts, and service requests — carry the full common set.

Every stateful entity exposes its lifecycle state in a `status` field whose permitted values are the exact uppercase strings enumerated for that entity in §3.

Path parameters are resolved left to right. For a nested path, each identifier segment is checked for existence in order, and the first that does not resolve produces the corresponding not-found error (for example, a missing district yields `ERR_BID_NOT_FOUND`, a missing budget yields `ERR_BUDGET_NOT_FOUND`). Each entity has its own not-found code: `ERR_BID_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`, `ERR_FISCAL_YEAR_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND`, `ERR_WORK_PLAN_LINE_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_COLLECTION_ACCOUNT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_SIGNATURE_NOT_FOUND`, `ERR_AMBASSADOR_NOT_FOUND`, and `ERR_SERVICE_REQUEST_NOT_FOUND`, each carrying HTTP 404.

### 2.5. Money, Precision, and Rounding

All monetary quantities are integer cents. Two derived quantities — a parcel's `weighted_base` and a budget's `estimate_rate` and `certified_rate` — are real numbers carried at full precision and are never themselves rounded to cents; rounding happens only when a rate is multiplied into a per-parcel assessment amount. Wherever a computation must land on whole cents — an assessment amount, a delinquency penalty, an interest accrual — the result is rounded **half up** to the nearest cent. The weighted-support ratio used to judge a petition is carried to four decimal places for its threshold comparison.

A pinned rule governs the fiscal-year levy total: each parcel's certified assessment is rounded to whole cents **first**, and only then are the per-parcel amounts summed. The total is never computed by summing raw rate-times-base products and rounding once at the end; the two orders can differ by cents, and only the round-then-sum order is correct.

### 2.6. Validation Order and Error Precedence

When more than one rule could reject a request, checks are evaluated in a fixed priority order, and the first failing check determines the returned error. The order is:

1. **Authentication** — headers present and role known, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role may invoke this endpoint per §2.1, else `ERR_UNAUTHORIZED`.
3. **Resource ownership** — for an entity-backed role acting on an owned resource (a `PropertyOwner` on their parcel's payment, dispute RESPOND/WITHDRAW, petition signature, or their service request; an `Ambassador` on a service-request START/RESOLVE), `X-User-ID` matches the owning foreign key, else `ERR_NOT_RESOURCE_OWNER`.
4. **Existence** — all path- and body-referenced resources exist, checked left to right, else the applicable `ERR_*_NOT_FOUND`.
5. **State** — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE`; a transition attempted on a terminal or otherwise closed dispute yields `ERR_DISPUTE_NOT_OPEN`; a collection-account transition against the wrong account state (delinquency assessment on a non-`BILLED` account, or write-off on a non-`DELINQUENT` account) yields `ERR_ACCOUNT_NOT_DELINQUENT`.
6. **Segregation of duties** — a petition vote cast by the same board member who verified it yields `ERR_SEGREGATION_OF_DUTIES`.
7. **Referential uniqueness** — the at-most-one constraints (`ERR_BUDGET_EXISTS`, `ERR_DISPUTE_ALREADY_OPEN`, `ERR_ALREADY_SIGNED`, `ERR_DUPLICATE_CATEGORY`) and the signing-parcel membership rule (`ERR_PARCEL_NOT_IN_DISTRICT`).
8. **Temporal windows** — the dispute filing window (`ERR_DISPUTE_WINDOW_CLOSED`) and the petition circulation deadline (`ERR_PETITION_DEADLINE_PASSED`).
9. **Structural constraints** — fiscal-year overlap (`ERR_FISCAL_YEAR_OVERLAP`), shift overlap/buffer (`ERR_SHIFT_OVERLAP`), budget balance at propose (`ERR_BUDGET_UNBALANCED`), and reallocation bounds (`ERR_INVALID_REALLOCATION`).
10. **Fiscal constraints** — non-negative levy (`ERR_NEGATIVE_LEVY`) and dispute-adjustment bounds (`ERR_ADJUSTMENT_EXCEEDS_ASSESSMENT`).
11. **Cross-entity state** — budget adopt and petition-open require an `ACTIVE` district (`ERR_BID_NOT_ACTIVE`); filing a dispute requires a `CERTIFIED` assessment (`ERR_ASSESSMENT_NOT_CERTIFIED`); assigning a service request requires an `ACTIVE` ambassador (`ERR_AMBASSADOR_NOT_ACTIVE`).
12. **Optimistic concurrency** — a stale expected version on a reallocation (`ERR_STALE_VERSION`).
13. **Body well-formedness** — required fields present, enums and types valid, and amounts strictly positive where required, else `ERR_VALIDATION`.

### 2.7. Optimistic Concurrency on Budget Reallocation

Moving cents from one work-plan line to another is the one operation guarded by optimistic concurrency control, because it recomputes against the caller's last-observed allocation totals and must not silently overwrite an intervening change. A reallocation request must carry `expected_budget_version` holding the `version` of the owning `Budget` that the client last read. If that value does not equal the budget's current `version` — because another reallocation or work-plan edit has advanced the budget since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a lost update to the balanced-allocation invariant. No other endpoint takes a version field.

### 2.8. The Logical Clock and Temporal Windows

All deadline, accrual, and window computations read a server logical clock rather than wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z` and never falls back to real time; an administrative test-driving capability sets it to an absolute instant supplied as `to_iso8601`. Day counts for delinquency and interest are whole calendar days measured from a due date; a signature or petition submission is timely only when the clock is strictly before the relevant deadline; a dispute is timely only within a fixed window after certification. The precise boundaries live with the workflows they govern in §3.

### 2.9. Cascading Consistency and Hierarchical Propagation

Several operations mutate more than one resource in a single request, and every such cascade is part of the contract. Adopting a budget certifies each estimated assessment and opens a collection account for it. Resolving a dispute downward re-syncs the collection account's billed principal, may convert it to a credit, and adjusts the fiscal-year ledger. Withdrawing a parcel can cancel a still-unpaid certified assessment and write off its account, reducing the certified levy. Resolving a service request charges its cost to a work-plan line. In every case, each entity the operation touches has its own `updated_at` refreshed and — for entities that carry one — its own `version` incremented; a parent's version is not a proxy for a child's. The specific cascades and their arithmetic are described where each workflow is defined.

## 3. Business Logic & Workflows

### 3.1. Forming a District and Enrolling Parcels

A `DistrictAdministrator` creates a district by supplying its legal `name`, a `boundary_description`, the `authorization_expires_at` instant at which its assessment authority lapses unless renewed, and the three weighting inputs `assessment_weight_value`, `assessment_weight_frontage`, and `assessment_weight_sqft`. The administrator may also supply `min_assessment_cents` and `max_assessment_cents`, the per-parcel floor and cap applied after weighting; when omitted these default to 50000 cents and 10000000 cents respectively. A new district begins life in `FORMING` status.

Member parcels are enrolled into a forming or active district by the administrator, each identified by its Assessor Parcel Number `apn` (unique within its district), with an `owner_name`, a `use_class`, the county-assessed market value `assessed_value_cents`, the street `linear_frontage_ft`, and the gross `building_sqft`. The `use_class` is one of `RETAIL`, `OFFICE`, `COMMERCIAL`, `MIXED`, `INDUSTRIAL`, `RESIDENTIAL_EXEMPT`, or `NONPROFIT_EXEMPT`. A parcel is born `ACTIVE`, belongs to its district through `bid_id`, and immediately has two derived properties computed: its exemption flag and its weighting base.

The `exempt` flag is true exactly when `use_class` is `RESIDENTIAL_EXEMPT` or `NONPROFIT_EXEMPT`; exempt parcels are excluded from the rate denominator and always receive a zero assessment. The `weighted_base` is computed as follows: for an exempt parcel it is zero; otherwise the system first forms a base-points figure by adding three terms — the value weight `assessment_weight_value` multiplied by the assessed value expressed in whole dollars (that is, `assessed_value_cents` divided by 100), plus the frontage weight `assessment_weight_frontage` multiplied by `linear_frontage_ft`, plus the square-foot weight `assessment_weight_sqft` multiplied by `building_sqft` — and then multiplies that base-points figure by the use-class multiplier for the parcel's class. The use-class multipliers are 1.25 for `RETAIL`, 1.15 for `MIXED`, 1.10 for `OFFICE`, 1.00 for `COMMERCIAL`, 0.90 for `INDUSTRIAL`, and 0 for both exempt classes. The `weighted_base` is kept at full precision. Because a parcel's inputs can change, its `weighted_base` is recomputed on update, and a snapshot of it is captured onto each assessment when that assessment is generated.

A `BoardMember` activates a forming district, transitioning it `FORMING → ACTIVE`. Activation requires that the district contain at least one `ACTIVE` parcel and that its `authorization_expires_at` be in the future relative to the logical clock — a violation of either precondition is rejected with `ERR_VALIDATION`; only once `ACTIVE` may the district accept fiscal years, budgets, and petitions. A parcel may be withdrawn from the district by the administrator, transitioning it `ACTIVE → WITHDRAWN`. Withdrawal has a downstream consequence when the parcel already carries a certified assessment on which no payment has yet been recorded: that assessment is cancelled (`CERTIFIED → CANCELLED`), its collection account is written off (`WRITTEN_OFF`), and the fiscal year's certified levy is reduced by that assessment's certified amount. A withdrawal is also the pivot that can turn a still-estimated assessment into a cancellation at adopt time, described in §3.3.

### 3.2. Fiscal Years, Budgets, and the Work Plan

The administrator opens a fiscal year on an active district by supplying a `year_label`, a `start_date`, an `end_date`, and the `assessment_due_date` on which the certified levy falls due on the tax bill. A fiscal year models the half-open interval running from `start_date` inclusive to `end_date` exclusive; a new fiscal year may not overlap any existing fiscal year of the same district, though exact adjacency — where one year's end equals the next year's start — is permitted. An overlapping interval is rejected with `ERR_FISCAL_YEAR_OVERLAP`. A fresh fiscal year begins `UPCOMING` with a `budget_status` of `NONE`, a `total_certified_levy_cents` and `collected_to_date_cents` of zero, and a `collection_status` of `OPEN`.

Each fiscal year has at most one budget, in a strict one-to-one relationship through `fiscal_year_id`; a second attempt is rejected with `ERR_BUDGET_EXISTS`. The administrator creates the budget by supplying the adopted spending ceiling `total_expenditure_cents` and the offsetting `other_revenue_cents` (grants, sponsorships, and other non-assessment revenue). On creation the budget is `DRAFT`, the fiscal year's `budget_status` becomes `DRAFT`, and the budget's `required_levy_cents` is computed as `total_expenditure_cents` minus `other_revenue_cents` — the amount the assessment must raise.

The work plan is a set of allocation lines added to a draft budget, each tied to its budget through `budget_id` and naming a `category` — one of `CLEAN`, `SAFE`, `MARKETING`, `ADMIN`, or `CONTINGENCY` — and an `allocated_amount_cents`. A category may appear at most once per budget; a duplicate is rejected with `ERR_DUPLICATE_CATEGORY`. Adding a line recomputes the budget's `allocated_total_cents` as the sum of its lines' `allocated_amount_cents` and increments the budget's `version`. Each line also tracks a `spent_amount_cents`, which starts at zero and grows only as field services are delivered (see §3.7).

Cents may be moved between two lines of a draft budget by a reallocation, which names a `from_category`, a `to_category`, the `amount_cents` to move, and the `expected_budget_version` described in §2.7. The moved amount is subtracted from the source line's allocation and added to the destination line's allocation, leaving `allocated_total_cents` unchanged, and the budget's `version` is incremented. The amount may not exceed the source line's current `allocated_amount_cents`; an over-draw, or a reference to a category that has no line, is rejected with `ERR_INVALID_REALLOCATION`. A reallocation whose `expected_budget_version` no longer matches the budget's current `version` is rejected with `ERR_STALE_VERSION`.

### 3.3. Proposing and Adopting the Budget

Proposing a budget is the act that turns the work plan into provisional assessments. The administrator proposes a draft budget only when three conditions hold: the work-plan allocations sum exactly to `total_expenditure_cents` — an imbalance is rejected with `ERR_BUDGET_UNBALANCED`; the `required_levy_cents` is at least zero — a negative levy (revenue exceeding expenditure) is rejected with `ERR_NEGATIVE_LEVY`; and at least one `ACTIVE` non-exempt parcel exists to bear the levy — when none exists the proposal is rejected with `ERR_VALIDATION`. On a successful proposal the budget transitions `DRAFT → PROPOSED`, its `proposed_at` timestamp is set, the fiscal year's `budget_status` becomes `PROPOSED`, and the budget's `version` is incremented.

At propose time the system computes the `estimate_rate` and generates one `ESTIMATED` assessment per `ACTIVE` non-exempt parcel. The `estimate_rate` is the `required_levy_cents` divided by the denominator, where the denominator is the sum of `weighted_base` over the district's parcels that are `ACTIVE` and non-exempt, evaluated as of the propose instant. Each such parcel's provisional charge is computed by taking the rate multiplied by that parcel's snapshotted `weighted_base` to get a raw amount, rounding that raw amount half up to whole cents, and then clamping the rounded figure to lie between the district's floor and cap — that is, the assessment is the larger of the floor `min_assessment_cents` and the smaller of the cap `max_assessment_cents` and the rounded raw amount. Each generated assessment records its `fiscal_year_id`, its `parcel_id`, its snapshot `weighted_base`, and the resulting `estimated_amount_cents`, and begins in `ESTIMATED` status. An exempt parcel produces no assessment (its charge would be zero and it is outside the denominator).

A proposed budget may be reverted to draft by the administrator, transitioning it `PROPOSED → DRAFT`: every `ESTIMATED` assessment for that fiscal year is deleted, the fiscal year's `budget_status` returns to `DRAFT`, and the budget's `version` is incremented. This lets staff correct the work plan before the board acts.

Adopting a budget is reserved to a `BoardMember` and is the moment the levy becomes real. Adoption requires that the owning district be `ACTIVE` — otherwise `ERR_BID_NOT_ACTIVE` — and that the budget be `PROPOSED`. Adoption re-evaluates the rate as of the adopt instant rather than reusing the estimate: the `certified_rate` is the `required_levy_cents` divided by the sum of `weighted_base` over parcels that are `ACTIVE` and non-exempt **at adopt time** (when that denominator is zero — every bearing parcel having withdrawn — the `certified_rate` is zero). This matters because a parcel may have withdrawn between propose and adopt, so the denominator — and therefore the rate and every per-parcel amount — can differ from the estimate. Adoption then cascades in two hops. First, each `ESTIMATED` assessment whose parcel is still `ACTIVE` is certified (`ESTIMATED → CERTIFIED`): its `certified_amount_cents` is computed with the same rate-times-base, round-half-up, then clamp-between-floor-and-cap procedure using the certified rate, and its `certified_at` is set to the clock; but an `ESTIMATED` assessment whose parcel has been `WITHDRAWN` since propose is instead cancelled (`ESTIMATED → CANCELLED`), receives no collection account, and is excluded from the levy total. Second, each certification creates a child `CollectionAccount` in `BILLED` status whose `billed_amount_cents` equals the assessment's `certified_amount_cents` and whose `due_date` is copied from the fiscal year's `assessment_due_date`. Finally the fiscal year's `total_certified_levy_cents` is set to the per-parcel-rounded sum of `certified_amount_cents` over its `CERTIFIED` and `ADJUSTED` assessments (`CANCELLED` assessments contribute nothing), the fiscal year's `budget_status` becomes `ADOPTED`, the fiscal year transitions to `ACTIVE`, the budget's `adopted_at` is set, and the budget's `version` is incremented.

### 3.4. Billing, Payment, Delinquency, and Write-Off

A collection account is the ledger for one certified assessment, linked through `assessment_id`, and is created already `BILLED`. Beyond its `billed_amount_cents` and `due_date` it tracks `penalty_accrued_cents`, `interest_accrued_cents`, `principal_paid_cents`, `total_paid_cents`, `credit_balance_cents`, a running `balance_due_cents`, and a `delinquent_since` instant. The outstanding principal at any moment is the `billed_amount_cents` less the `principal_paid_cents`, and the `balance_due_cents` is that outstanding principal plus the accrued penalty plus the accrued interest, less any credit balance applied, floored at zero (a fully credited account reports `balance_due_cents` of zero rather than a negative figure).

Payments are posted by a `TaxCollector` or by the owning `PropertyOwner`, and only against an account still in `BILLED` or `DELINQUENT` status; a payment on an account that is already `PAID`, `CREDIT`, or `WRITTEN_OFF` is rejected with `ERR_INVALID_STATE`. A payment names an `amount_cents` (which must be strictly positive) and optionally a `method` — one of `TAX_ROLL`, `ACH`, `CHECK`, or `CARD`, defaulting to `TAX_ROLL`. Each payment is stamped with a `posted_at` instant from the logical clock and is allocated through a fixed waterfall that consumes buckets in one pinned order: interest first, then penalty, then principal. Concretely, the payment amount is applied to accrued interest up to the interest owed and that portion is recorded as `applied_to_interest_cents`; whatever remains is applied to the accrued penalty up to the penalty owed as `applied_to_penalty_cents`; whatever still remains is applied to outstanding principal as `applied_to_principal_cents`, which increases `principal_paid_cents`. The full `amount_cents` is added to `total_paid_cents`. If anything remains after principal is fully retired, that surplus is added to `credit_balance_cents` as an overpayment. When a payment clears the outstanding principal together with all accrued interest and penalty, the account transitions to `PAID` (from either `BILLED` or `DELINQUENT`); an overpayment beyond the full balance instead moves the account to `CREDIT` with the surplus recorded as its credit balance. On any payment the fiscal year's `collected_to_date_cents` accumulates the net cash (payments less refunds), and once that running figure reaches or exceeds the fiscal year's `total_certified_levy_cents` the fiscal year's `collection_status` flips to `FULLY_COLLECTED`.

Interest accrues daily on outstanding principal. The day count as of any reference instant is the whole number of calendar days from the `due_date` to that instant, never less than zero (computed as the floor of the elapsed days, floored at zero). Interest as of a reference instant is the outstanding principal multiplied by the daily interest rate of 0.0005 multiplied by that day count, rounded half up to whole cents. An account becomes eligible for delinquency only once its day count as of the current clock strictly exceeds the grace period of 30 days. A `TaxCollector` marks a past-grace, still-owing `BILLED` account delinquent, transitioning it `BILLED → DELINQUENT`: this applies a one-time penalty equal to the `billed_amount_cents` multiplied by the penalty rate of 0.10, rounded half up to whole cents and recorded in `penalty_accrued_cents`, and sets `delinquent_since` to the account's `due_date`. Delinquency assessment on an account that is not `BILLED`, or that has not yet passed the grace period, or that is already fully credited, is rejected with `ERR_ACCOUNT_NOT_DELINQUENT`; attempting it on an account that is already `DELINQUENT` is rejected with `ERR_ALREADY_DELINQUENT`. A `TaxCollector` may write off a delinquent account, transitioning it `DELINQUENT → WRITTEN_OFF`, which freezes its balance and excludes it from any further re-evaluation of the fiscal year's collection status; a write-off attempted on a non-delinquent account is rejected with `ERR_ACCOUNT_NOT_DELINQUENT`.

A read-only payoff quote projects the account forward without mutating it. Given a client-supplied `as_of_date`, the quote reports the `collection_account_id`, the echoed `as_of_date`, the `principal_outstanding_cents`, the `penalty_cents`, the `interest_cents` computed to that future date using the same daily-interest formula and day count, and the `quoted_balance_cents` that would be owed on that date (also floored at zero). Because it is a projection, the quote never changes stored balances; the account's realized interest is only ever advanced when an actual payment posts, using the payment's `posted_at` as the reference instant.

### 3.5. Assessment Disputes

Only a `PropertyOwner` may file a dispute, and only against their own parcel's assessment while that assessment is `CERTIFIED` — a dispute against an assessment in any other status is rejected with `ERR_ASSESSMENT_NOT_CERTIFIED`. Filing must fall within the dispute window: strictly within 45 days after the assessment's `certified_at` instant; once that window has passed the filing is rejected with `ERR_DISPUTE_WINDOW_CLOSED`. At most one non-terminal dispute may exist per assessment; a second is rejected with `ERR_DISPUTE_ALREADY_OPEN`. A filing supplies the owner's asserted correct market value `claimed_value_cents`, the `requested_amount_cents` they believe the assessment should be, and an optional free-text `reason`; the new dispute begins `SUBMITTED` with `filed_at` set to the clock.

A dispute advances through a single transition capability whose `action` selects the move; a transition against a dispute that has already reached a terminal outcome is rejected with `ERR_DISPUTE_NOT_OPEN`, and any action not defined from the current state yields `ERR_INVALID_STATE`. A `DistrictAdministrator` moves a submitted dispute into review (`SUBMITTED → UNDER_REVIEW`) and may request more information (`UNDER_REVIEW → INFO_REQUESTED`). The owning `PropertyOwner` responds to such a request (`INFO_REQUESTED → UNDER_REVIEW`), and this review cycle may repeat between `UNDER_REVIEW` and `INFO_REQUESTED` any number of times. The owner may also withdraw the dispute (to `WITHDRAWN`) from any of `SUBMITTED`, `UNDER_REVIEW`, or `INFO_REQUESTED`. Owner-driven actions — responding and withdrawing — require that the acting owner own the disputed assessment's parcel, else `ERR_NOT_RESOURCE_OWNER`.

A `DistrictAdministrator` resolves a dispute from `UNDER_REVIEW` by supplying a `decision`. A denial (`UNDER_REVIEW → RESOLVED_DENIED`) sets `resolved_at` and leaves the assessment untouched. An adjustment (`UNDER_REVIEW → RESOLVED_ADJUSTED`) requires a `resolved_amount_cents` that lies between zero and the assessment's current `certified_amount_cents` inclusive; a value outside that range is rejected with `ERR_ADJUSTMENT_EXCEEDS_ASSESSMENT`. On an adjustment the dispute records `resolved_amount_cents` and `resolved_at`, and a three-hop cascade fires. First, the linked assessment transitions `CERTIFIED → ADJUSTED` and its `certified_amount_cents` is set to the resolved amount. Second, the child collection account's `billed_amount_cents` is re-synced to the new certified amount and its `balance_due_cents` recomputed; if the account has now been overpaid relative to the reduced principal it moves to `CREDIT`, the overpayment is recorded in `credit_balance_cents`, and a refund is recorded; alternatively, if the reduced principal is now exactly retired with no penalty outstanding (and the account was `BILLED` or `DELINQUENT`), the account moves to `PAID`. Third, the fiscal year's `total_certified_levy_cents` and `collected_to_date_cents` are adjusted by the resulting deltas so the ledger stays exact.

### 3.6. Renewal Petitions and the Board Vote

A district's assessment authority expires at `authorization_expires_at` unless renewed through a property-owner petition. A `DistrictAdministrator` opens a renewal petition on an `ACTIVE` district, which transitions the district `ACTIVE → RENEWAL_PENDING` and creates a `CIRCULATING` petition; opening requires the district be `ACTIVE` (`ERR_BID_NOT_ACTIVE`) and that no other petition for the district is already in `CIRCULATING`, `SUBMITTED`, or `VERIFIED`. The opener supplies the `circulation_deadline` and may override the `required_threshold_pct` (the minimum weighted support fraction to pass, defaulting to 0.50) and the `renewal_term_months` (months added to the authorization on approval, defaulting to 60).

While a petition circulates, a `PropertyOwner` records one signature per parcel by supplying the signing `parcel_id` and a boolean `support` (true for support, false for opposition); each signature references its petition through `petition_id` and is stamped `signed_at` from the clock. Signatures may be listed and filtered by `petition_id` and by `parcel_id`. A parcel may sign a given petition at most once — a repeat is rejected with `ERR_ALREADY_SIGNED` — and the signing parcel must be an `ACTIVE` parcel of the petition's district, else `ERR_PARCEL_NOT_IN_DISTRICT`. Signatures are accepted only while the logical clock is strictly before the `circulation_deadline`; at or after it, both further signing and submission are rejected with `ERR_PETITION_DEADLINE_PASSED`. The administrator submits the petition to close circulation (`CIRCULATING → SUBMITTED`), which is likewise permitted only strictly before the deadline.

A `BoardMember` verifies a submitted petition, at which point the system computes the assessment-weighted support fraction `weighted_support_pct`. The basis for that fraction is the district's most recent adopted fiscal year: among the district's fiscal years whose budget is `ADOPTED`, select the one with the latest `end_date`, breaking a tie by the later `created_at`; if the district has no adopted fiscal year, the support fraction is zero. The total weight is the sum of `certified_amount_cents` over that basis year's assessments in `CERTIFIED` or `ADJUSTED` status. The support weight is the sum of `certified_amount_cents` over exactly those assessments whose parcel cast a supporting signature (a `PetitionSignature` on this petition with `support` true). The `weighted_support_pct` is the support weight divided by the total weight, carried to four decimals; if the total weight is zero the fraction is zero. Verification records the acting board member's `X-User-ID` as `verified_by_user_id`. If the fraction is at least the `required_threshold_pct`, the petition transitions `SUBMITTED → VERIFIED`; if it falls short, the petition transitions `SUBMITTED → FAILED` and the district transitions `RENEWAL_PENDING → EXPIRED`.

The board vote on a verified petition is the four-eyes control. A `BoardMember` casts a `decision` of APPROVE or REJECT, but the voting member's `X-User-ID` must differ from the petition's `verified_by_user_id`; a vote cast by the same member who verified is rejected with `ERR_SEGREGATION_OF_DUTIES`. An approval transitions the petition `VERIFIED → APPROVED`, extends the district's `authorization_expires_at` by `renewal_term_months`, and returns the district `RENEWAL_PENDING → ACTIVE`. A rejection transitions the petition `VERIFIED → REJECTED` and transitions the district `RENEWAL_PENDING → EXPIRED`, a terminal state in which the district can no longer adopt new budgets or open petitions.

### 3.7. Ambassadors, Shifts, and Service Delivery

Field service is delivered by ambassadors attached to a district through `bid_id`. A `DistrictAdministrator` adds an ambassador with a `name` and a `service_role` — one of `CLEAN`, `SAFE`, or `OUTREACH` — starting `ACTIVE`, and may later deactivate them (`ACTIVE → INACTIVE`); a deactivated ambassador cannot be assigned work. An ambassador's schedule is a set of shifts, each with a `zone`, a `start_at`, and an `end_at`, created `SCHEDULED`. Shifts on one ambassador are treated as closed intervals that may not overlap, and consecutive shifts must be separated by at least the shift buffer of 30 minutes; a new shift that overlaps or falls within that half-hour gap of an existing scheduled shift of the same ambassador is rejected with `ERR_SHIFT_OVERLAP`.

Service requests — including inbound 311 tickets — are logged against a district by a `DistrictAdministrator` or a `PropertyOwner`. A request carries a `category` (`CLEAN`, `SAFE`, or `OTHER`), a `source` (`WALK_IN`, `PHONE`, `THREE_ONE_ONE`, or `EMAIL`), an optional `external_ref` for linkage to an external 311 ticket, and an optional `description`, and begins `OPEN`. A request moves through a single transition capability keyed by `action`. The administrator assigns an open request to an ambassador by supplying an `ambassador_id`; assignment (`OPEN → ASSIGNED`) sets `assigned_ambassador_id` and requires that the target ambassador belong to the same district and be `ACTIVE`, else `ERR_AMBASSADOR_NOT_ACTIVE`. The assigned `Ambassador` starts the work (`ASSIGNED → IN_PROGRESS`) and later resolves it (`IN_PROGRESS → RESOLVED`); both require that the acting ambassador's `X-User-ID` equal the request's `assigned_ambassador_id`, else `ERR_NOT_RESOURCE_OWNER`. Resolution supplies the `logged_cost_cents` incurred and the `work_plan_category` to charge, and this cost is reconciled against the budget: the target line is the work-plan line whose `category` equals `work_plan_category` on the adopted budget of the district's most recent adopted fiscal year (the same basis-year selector used for petition verification — latest `end_date`, tie-broken by later `created_at`); the request records its `logged_cost_cents` and `work_plan_category`, and that line's `spent_amount_cents` is increased by the logged cost. Resolution requires that such an adopted budget with a matching line exist; if no matching work-plan line can be found the resolution is rejected with `ERR_WORK_PLAN_LINE_NOT_FOUND`. The administrator closes a resolved request (`RESOLVED → CLOSED`), and may cancel a request that is still `OPEN` or `ASSIGNED` (to `CANCELLED`).

### 3.8. Financial Reporting

A `DistrictAdministrator` or `BoardMember` may read a computed budget-versus-actual report for a fiscal year. The report restates the fiscal year's `fiscal_year_id`, its `total_certified_levy_cents`, its `collected_to_date_cents`, and its `collection_status`, and adds a `by_category` breakdown. Each category entry carries the line's `category` label and pairs the work plan's `allocated_amount_cents` with the `spent_amount_cents` reconciled from resolved service requests, and reports the variance as the allocated amount minus the spent amount — surfaced in both a `variance_cents` field and a duplicate `variance` field of the same value — so the board can see under- and over-spend per service line. The `by_category` entries are ordered by their work-plan line's `created_at` ascending.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201 with the created resource; state transitions and other mutations that operate on an existing resource return HTTP 200 with the updated resource; reads return HTTP 200. The table lists the HTTP surface only; request bodies, response shapes, and side effects are specified in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Set the server logical clock to an absolute UTC instant | DistrictAdministrator, BoardMember, TaxCollector, PropertyOwner, Ambassador (any authenticated role) |
| POST | `/business-improvement-districts` | Create a district (FORMING) | DistrictAdministrator |
| GET | `/business-improvement-districts/{id}` | Get a district | DistrictAdministrator, BoardMember, TaxCollector, PropertyOwner, Ambassador |
| POST | `/business-improvement-districts/{id}/activate` | Activate a FORMING district | BoardMember |
| POST | `/business-improvement-districts/{id}/parcels` | Register a member parcel | DistrictAdministrator |
| GET | `/business-improvement-districts/{id}/parcels` | List parcels of a district (filterable by `status`) | DistrictAdministrator, BoardMember |
| GET | `/parcels/{id}` | Get a parcel | DistrictAdministrator, BoardMember, PropertyOwner |
| POST | `/parcels/{id}/withdraw` | Withdraw a parcel from the district | DistrictAdministrator |
| POST | `/business-improvement-districts/{id}/fiscal-years` | Create a fiscal year (overlap-checked) | DistrictAdministrator |
| GET | `/business-improvement-districts/{id}/fiscal-years` | List fiscal years | DistrictAdministrator, BoardMember |
| GET | `/fiscal-years/{id}` | Get a fiscal year | DistrictAdministrator, BoardMember |
| GET | `/fiscal-years/{id}/financial-report` | Budget-vs-actual financial report | DistrictAdministrator, BoardMember |
| POST | `/fiscal-years/{id}/budget` | Create the DRAFT budget for a fiscal year | DistrictAdministrator |
| GET | `/fiscal-years/{id}/budget` | Get the budget of a fiscal year (returned as an array envelope of the fiscal year's budgets, zero or one element) | DistrictAdministrator, BoardMember |
| GET | `/budgets/{id}` | Get a budget | DistrictAdministrator, BoardMember |
| POST | `/budgets/{id}/work-plan-lines` | Add a work-plan allocation line (DRAFT only) | DistrictAdministrator |
| GET | `/budgets/{id}/work-plan-lines` | List work-plan lines | DistrictAdministrator, BoardMember |
| POST | `/budgets/{id}/reallocations` | Move cents between two work-plan lines (OCC) | DistrictAdministrator |
| POST | `/budgets/{id}/propose` | Propose the budget: balance-check then generate ESTIMATED assessments | DistrictAdministrator |
| POST | `/budgets/{id}/adopt` | Adopt the budget: certify assessments and open collection accounts | BoardMember |
| POST | `/budgets/{id}/revert` | Revert a PROPOSED budget to DRAFT, discarding estimates | DistrictAdministrator |
| GET | `/assessments/{id}` | Get an assessment | DistrictAdministrator, BoardMember, PropertyOwner |
| GET | `/assessments` | List assessments by parcel and/or fiscal year and/or `status` | DistrictAdministrator, BoardMember, PropertyOwner |
| GET | `/assessments/{id}/collection-account` | Get the collection account for an assessment (returned as an array envelope, zero or one element) | DistrictAdministrator, BoardMember, TaxCollector, PropertyOwner |
| GET | `/collection-accounts/{id}` | Get a collection account | DistrictAdministrator, BoardMember, TaxCollector, PropertyOwner |
| GET | `/collection-accounts/{id}/payoff-quote` | Projected payoff as of a supplied date (read-only) | DistrictAdministrator, TaxCollector, PropertyOwner |
| POST | `/collection-accounts/{id}/payments` | Post a payment (waterfall allocation) | TaxCollector, PropertyOwner |
| GET | `/collection-accounts/{id}/payments` | List payments on an account | DistrictAdministrator, BoardMember, TaxCollector, PropertyOwner |
| POST | `/collection-accounts/{id}/assess-delinquency` | Mark a past-grace unpaid account DELINQUENT and apply penalty | TaxCollector |
| POST | `/collection-accounts/{id}/write-off` | Write off a delinquent account | TaxCollector |
| POST | `/assessments/{id}/disputes` | File a dispute on a certified assessment | PropertyOwner |
| GET | `/assessments/{id}/disputes` | List disputes for an assessment | DistrictAdministrator, BoardMember, PropertyOwner |
| GET | `/disputes/{id}` | Get a dispute | DistrictAdministrator, BoardMember, PropertyOwner |
| POST | `/disputes/{id}/transition` | Advance a dispute (REVIEW/REQUEST_INFO/RESPOND/RESOLVE/WITHDRAW) | DistrictAdministrator, PropertyOwner |
| POST | `/business-improvement-districts/{id}/renewal-petitions` | Open a renewal petition | DistrictAdministrator |
| GET | `/business-improvement-districts/{id}/renewal-petitions` | List renewal petitions | DistrictAdministrator, BoardMember |
| GET | `/renewal-petitions/{id}` | Get a renewal petition | DistrictAdministrator, BoardMember, PropertyOwner |
| POST | `/renewal-petitions/{id}/signatures` | Record a parcel's signature | PropertyOwner |
| GET | `/petition-signatures` | List petition signatures by petition and/or parcel | DistrictAdministrator, BoardMember |
| GET | `/petition-signatures/{id}` | Get a single petition signature | DistrictAdministrator, BoardMember |
| POST | `/renewal-petitions/{id}/submit` | Close circulation and submit for verification | DistrictAdministrator |
| POST | `/renewal-petitions/{id}/verify` | Verify weighted support against threshold | BoardMember |
| POST | `/renewal-petitions/{id}/vote` | Board vote on a verified petition (four-eyes SoD) | BoardMember |
| POST | `/business-improvement-districts/{id}/ambassadors` | Add an ambassador | DistrictAdministrator |
| POST | `/ambassadors/{id}/deactivate` | Deactivate an ambassador (ACTIVE→INACTIVE) | DistrictAdministrator |
| GET | `/business-improvement-districts/{id}/ambassadors` | List ambassadors | DistrictAdministrator, BoardMember |
| GET | `/ambassadors/{id}` | Get an ambassador | DistrictAdministrator, BoardMember, Ambassador |
| POST | `/ambassadors/{id}/shifts` | Schedule an ambassador shift (overlap + buffer checked) | DistrictAdministrator |
| GET | `/ambassadors/{id}/shifts` | List an ambassador's shifts | DistrictAdministrator, BoardMember, Ambassador |
| POST | `/business-improvement-districts/{id}/service-requests` | Log a service request / 311 ticket | DistrictAdministrator, PropertyOwner |
| GET | `/service-requests` | List service requests by district and/or assigned ambassador and/or `status` | DistrictAdministrator, BoardMember, Ambassador |
| GET | `/service-requests/{id}` | Get a service request | DistrictAdministrator, BoardMember, Ambassador, PropertyOwner |
| POST | `/service-requests/{id}/transition` | Advance a service request (ASSIGN/START/RESOLVE/CLOSE/CANCEL) | DistrictAdministrator, Ambassador |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_VALIDATION | 422 |
| ERR_BID_NOT_FOUND | 404 |
| ERR_PARCEL_NOT_FOUND | 404 |
| ERR_FISCAL_YEAR_NOT_FOUND | 404 |
| ERR_BUDGET_NOT_FOUND | 404 |
| ERR_WORK_PLAN_LINE_NOT_FOUND | 404 |
| ERR_ASSESSMENT_NOT_FOUND | 404 |
| ERR_COLLECTION_ACCOUNT_NOT_FOUND | 404 |
| ERR_DISPUTE_NOT_FOUND | 404 |
| ERR_PETITION_NOT_FOUND | 404 |
| ERR_SIGNATURE_NOT_FOUND | 404 |
| ERR_AMBASSADOR_NOT_FOUND | 404 |
| ERR_SERVICE_REQUEST_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_DISPUTE_NOT_OPEN | 409 |
| ERR_ACCOUNT_NOT_DELINQUENT | 409 |
| ERR_ALREADY_DELINQUENT | 409 |
| ERR_BID_NOT_ACTIVE | 409 |
| ERR_ASSESSMENT_NOT_CERTIFIED | 409 |
| ERR_AMBASSADOR_NOT_ACTIVE | 409 |
| ERR_BUDGET_EXISTS | 409 |
| ERR_DISPUTE_ALREADY_OPEN | 409 |
| ERR_ALREADY_SIGNED | 409 |
| ERR_DUPLICATE_CATEGORY | 409 |
| ERR_PARCEL_NOT_IN_DISTRICT | 409 |
| ERR_FISCAL_YEAR_OVERLAP | 409 |
| ERR_SHIFT_OVERLAP | 409 |
| ERR_DISPUTE_WINDOW_CLOSED | 422 |
| ERR_PETITION_DEADLINE_PASSED | 422 |
| ERR_BUDGET_UNBALANCED | 422 |
| ERR_INVALID_REALLOCATION | 422 |
| ERR_NEGATIVE_LEVY | 422 |
| ERR_ADJUSTMENT_EXCEEDS_ASSESSMENT | 422 |
| ERR_STALE_VERSION | 412 |
