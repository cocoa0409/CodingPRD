# Deposit Alt Lease Insurance API — Product Requirements Document

## 1. Introduction

Security deposits lock up a renter's cash for the duration of a lease and give landlords only a single, blunt recovery instrument when something goes wrong. This program replaces that cash deposit with an ongoing insurance relationship: a renter is underwritten once at application time, pays a recurring fee instead of a lump sum, and the landlord recovers unpaid rent or property damage by filing a claim against the renter's policy rather than drawing down an escrowed deposit. The platform sits between three physical parties — the landlord who lists a property and eventually files claims, the renter who applies for coverage and pays premiums, and a set of internal operating roles (underwriting, claims adjustment, compliance, and platform administration) who run the underwriting, adjudication, and recovery machinery — and it must keep all of them synchronized against a single ledger of coverage, invoices, and payouts.

The domain has three intertwined lifecycles that this document specifies precisely. First, a property must be enrolled in the program and a renter's application underwritten before any coverage exists; underwriting is state-regulated, so every state a property sits in must have an explicit compliance configuration before enrollment is even attempted. Second, once a policy is active it generates a recurring premium-invoice cycle that can lapse and reinstate, mirroring a real billing relationship rather than a one-time purchase. Third, when a landlord files a claim, the platform must adjudicate it, disburse a payout under a strict separation between the adjuster who approves the claim and the adjuster who moves the money, and — when the loss traces back to the renter's own default — pursue subrogation recovery from that renter. Every one of these lifecycles produces cross-entity side effects (a payout disbursement changes the policy's available coverage and the property's paid-claims total in the same transaction) that this document calls out explicitly wherever they occur, because the implementer will never see the underlying seed tables — only this narrative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting an `X-User-Role` value that is not one of the roles enumerated below, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request from an authenticated caller whose role is not permitted to perform the specific operation being attempted is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The declared roles are `Anonymous`, `Landlord`, `Renter`, `UnderwritingAgent`, `ClaimsAdjuster`, `ComplianceOfficer`, and `PlatformAdmin`.

- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque identifier not tied to any persisted entity; it is used only for self-registration flows and is not compared against any resource's ownership field.
- When `X-User-Role` is `Landlord`, `X-User-ID` is the `id` of the acting `Landlord`; ownership checks on any resource that references a `Landlord` (directly, or transitively through a `Property`) compare the resource's foreign-key chain back to `X-User-ID`.
- When `X-User-Role` is `Renter`, `X-User-ID` is the `id` of the acting `Renter`; ownership checks on any resource that references a `Renter` (directly, or transitively through a `RenterEnrollment`) compare the resource's foreign-key chain back to `X-User-ID`.
- When `X-User-Role` is `UnderwritingAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; it is simply the operator who decides manual-review applications and adjusts live coverage limits.
- When `X-User-Role` is `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier. The server records it as `reviewing_adjuster_id` on the `Claim` when that adjuster approves or denies it, and as `disbursing_adjuster_id` on the `Payout` when that adjuster disburses it — these two recorded identifiers are compared to each other (never to a persisted entity's `id`) to enforce segregation of duties.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, used for property program-status decisions, state-compliance configuration, and subrogation-case administration.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, used for the billing sweep, the logical clock, and reversal operations.

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

List endpoints accept `limit` and `offset` query parameters. When omitted, `limit` defaults to 10 and `offset` defaults to 0. `limit` must be between 1 and 100 inclusive; `offset` must be 0 or greater. List results are sorted by `created_at` ascending unless a subsection below states otherwise; ties in `created_at` are broken by `id` ascending. The response `meta` object for list endpoints carries `limit`, `offset`, `total_count` (the total number of matching records regardless of pagination window), and `has_more` (whether records exist beyond the current window).

### 2.4. Resource Identity, Timestamps, and Optimistic Concurrency

Every entity in this system — with one exception noted below — carries four common properties: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits set at creation; `updated_at`, an ISO 8601 UTC timestamp updated on every mutation; and `version`, an integer that starts at 1 and increments by 1 on every mutating write to that record. The sole exception is `StateComplianceRule`, which carries only `id` and `created_at` — it has no `updated_at` and no `version`, because it is treated as static reference configuration rather than a mutable operational record. Nearly every entity also carries its own lifecycle field, named `status` in each case, whose declared values are enumerated in the relevant §3 subsection alongside its state machine.

Optimistic concurrency control (OCC) protects exactly one write path in this system: adjusting a `Policy`'s coverage limit. A request to adjust a policy's coverage limit must carry `expected_policy_version`, the client's last-observed value of that policy's `version`. If `expected_policy_version` does not match the policy's current `version` at the moment of the write — because a coverage-limit adjustment, a claim approval, a payout disbursement or reversal, or an invoice-driven status change has advanced it in the meantime — the adjustment is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412), and the client must re-read the policy and retry with the fresh version. No other write endpoint in this system takes an expected-version field.

### 2.5. Path Resolution and Reverse-Reachability

Every endpoint that takes one or more identifiers — whether as a URL path segment or as a body field referencing another resource — validates those identifiers left to right along the path, then top to bottom through the request body. A path segment such as `{id}` in `/properties/{id}` must resolve to an existing `Property` before any body field is examined; a body field such as `landlord_id`, `property_id`, `renter_id`, `policy_id`, `claim_id`, `subrogation_case_id`, or `state_code` must likewise resolve before any state or business-rule check runs. Each not-found condition carries its own error identifier: an unresolvable landlord yields `ERR_LANDLORD_NOT_FOUND`, a renter yields `ERR_RENTER_NOT_FOUND`, a property yields `ERR_PROPERTY_NOT_FOUND`, a renter enrollment yields `ERR_RENTER_ENROLLMENT_NOT_FOUND`, a policy yields `ERR_POLICY_NOT_FOUND`, an invoice yields `ERR_INVOICE_NOT_FOUND`, a claim yields `ERR_CLAIM_NOT_FOUND`, a payout yields `ERR_PAYOUT_NOT_FOUND`, a subrogation case yields `ERR_SUBROGATION_CASE_NOT_FOUND`, and a recovery payment yields `ERR_RECOVERY_PAYMENT_NOT_FOUND` — all at HTTP 404.

Several endpoints exist purely to walk a foreign-key relationship in reverse: listing the properties owned by a landlord, listing the enrollments tied to a property or a renter, finding the policy created for an enrollment, listing a policy's invoices or claims, listing a claim's payouts or subrogation cases, and listing a subrogation case's recovery payments. These reverse-reachability endpoints establish their parent collection segment (for example, resolving the landlord before listing its properties) using the same left-to-right resolution order described above, and they apply the same pagination defaults as any other list endpoint — except finding the policy for an enrollment, which resolves to at most one record and always responds with the fixed default window (`limit` 10, `offset` 0) regardless of any `limit`/`offset` query parameters supplied.

The overall validation order applied to every request, regardless of endpoint, is: authentication first (`ERR_UNAUTHENTICATED`), then authorization (`ERR_UNAUTHORIZED`), then input shape and type checking (`ERR_VALIDATION`), then existence of every referenced resource in path-then-body order, then the state or transition-eligibility check for the target resource (`ERR_INVALID_STATE`), and only after all of that do the endpoint's own business-rule checks run in the order documented in the relevant §3 subsection.

### 2.6. Monetary Precision and Rounding

All monetary fields in this system are denominated in integer cents (`_cents` suffix) — there are no fractional-cent amounts anywhere in storage or in API responses. Wherever a calculation produces a value with fractional cents before it can be stored, that value is rounded using round-half-up (a value exactly at the halfway point between two cents rounds to the higher cent) unless a specific calculation states it needs no rounding because its inputs are already integer cents. The `underwriting_risk_score` calculation likewise produces an integer, rounded half-up. `max_monthly_fee_pct_of_rent`, used to compute a state's fee ceiling, is a fraction between 0 (exclusive) and 1 (inclusive) applied against `monthly_rent_cents` and then floored to the nearest whole cent — never rounded up or half-up — when establishing the ceiling itself.

### 2.7. State Compliance as a Cross-Cutting Gate

Every `Property` carries a `state_code` — a two-letter uppercase US state abbreviation such as `CA`, `NY`, or `TX` — and every state referenced by a property must have a corresponding `StateComplianceRule` before that property's renters can apply for coverage. A `StateComplianceRule` declares whether `enrollment_allowed` for that state at all, a `max_monthly_fee_pct_of_rent` ceiling, a `cooling_off_buffer_days` minimum gap for re-enrollment after termination, and an informational `mandatory_alternative_offering` flag surfaced in compliance reporting to indicate whether landlords in that state are legally required to offer the deposit alternative alongside a traditional cash deposit. Filing a new renter enrollment against a property whose state has no configured rule is rejected with `ERR_STATE_NOT_CONFIGURED` (HTTP 422); filing against a property whose state's rule has `enrollment_allowed` set to false is rejected with `ERR_STATE_ENROLLMENT_PROHIBITED` (HTTP 422). Both of these state-compliance checks apply specifically to new-enrollment creation and are evaluated before the property-active and lease-overlap checks described in §3.1 and §3.2.

The state's fee ceiling reappears at two later points in the lifecycle: when an enrollment auto-approves or is manually approved (§3.2), and whenever a policy's coverage limit is adjusted after issuance (§3.3) — both moments recompute the would-be monthly fee and compare it against the ceiling before committing.

### 2.8. Coverage Ledger Integrity

Each `Policy` tracks two distinct views of its remaining coverage capacity, and the distinction between them is a first-class business rule rather than an implementation detail. The gross available coverage is a forward-looking reservation: it subtracts every claim that has reached `APPROVED` or `CLOSED` from the policy's coverage limit, whether or not that claim's payout has actually been paid out yet. The net available coverage is a cash-actually-moved view: it subtracts only the payouts that have actually reached `DISBURSED` status. These two figures necessarily diverge whenever a claim has been approved but its payout is still sitting in `PENDING` — gross has already reserved the exposure, net has not yet felt it. Both are recomputed from scratch off the underlying claim and payout records, never incrementally patched, whenever a claim is approved, whenever a payout is disbursed or reversed, and whenever a coverage-limit adjustment is applied.

A conserved-quantity invariant ties the policy's coverage limit to its net-available figure at all times: the coverage limit always equals the net available coverage plus the sum of every non-reversed, disbursed payout's amount for that policy. Reversing a payout is the compensating action that restores this invariant — it recomputes `net_available_coverage_cents` back to its pre-disbursement value rather than merely adding the reversed amount back in an ad hoc way, and it likewise restores the affected property's paid-claims total to its pre-disbursement value (see §2.9 for the full disbursement cascade). A parallel invariant governs subrogation: a case's original demand amount always equals its current outstanding balance plus the sum of every non-reversed, succeeded recovery payment against that case, and reversing a recovery payment is the compensating action there too — it restores the outstanding balance and, if the case had already reached `PAID_IN_FULL`, reverts it back to `DEMAND_SENT`.

### 2.9. Segregation of Duties and Disbursement Cascade

The claims-and-payout pipeline enforces a strict separation between the operator who adjudicates a claim and the operator who moves money against it. The `ClaimsAdjuster` identity recorded when a claim is approved or denied is compared, at disbursement time, against the `ClaimsAdjuster` identity attempting to disburse that claim's payout; if the two `X-User-ID` values match, the disbursement is rejected with `ERR_SOD_VIOLATION` (HTTP 403) regardless of how correct the underlying payout amount is.

Disbursing a payout is also this system's deepest cascade: a single disbursement action mutates the payout itself, then the policy that funds it, then the property that the underlying claim traces back to, and finally bubbles a state change up to the claim. Concretely, disbursing a `PENDING` payout (1) marks the payout `DISBURSED` and records who disbursed it and when; (2) recomputes the funding policy's net available coverage to reflect the newly-moved cash; (3) recomputes the property's `total_paid_claims_cents` (aggregated across every payout on every claim on every policy tracing back to that property, filtered to `DISBURSED` status) to include the new amount; and (4) closes the underlying claim from `APPROVED` to `CLOSED` as a system-driven bubble-up once its payout has actually landed. Reversing a payout unwinds hops (2) and (3) back to their pre-disbursement values but does not reopen the claim.

## 3. Business Logic & Workflows

### 3.1. Landlord and Property Onboarding

Anyone may self-register as a `Landlord` by supplying `full_name`, `email`, and `phone_number`; `email` must be unique across all landlords. A `Landlord` then lists a property by submitting `landlord_id`, `address_line1`, `city`, `state_code`, `monthly_rent_cents`, and `property_type` — `property_type` must be one of `SINGLE_FAMILY`, `MULTI_FAMILY`, or `CONDO`, and `monthly_rent_cents` must be a positive integer. A newly listed property starts in `PENDING_REVIEW` with `total_paid_claims_cents` initialized to zero, and cannot receive renter applications until a `ComplianceOfficer` activates it.

A `ComplianceOfficer` moves a property from `PENDING_REVIEW` to `ACTIVE` by supplying an `action` of `ACTIVATE`; from `ACTIVE`, the same officer can `TERMINATE` the property, which records the current clock time as `terminated_at`. Termination is not necessarily permanent: a `TERMINATED` property can be re-activated with another `ACTIVATE` action, but only once a cooling-off period has fully elapsed. That period is state-specific — it is the `cooling_off_buffer_days` value from the `StateComplianceRule` governing the property's `state_code`, or a default of 30 days if no such rule has been configured for that state — and re-activation is measured from `terminated_at`: the current clock time must be at or after `terminated_at` plus that many days. Attempting to reactivate before the buffer has elapsed is rejected with `ERR_REENROLLMENT_COOLDOWN_ACTIVE` (HTTP 409); a successful reactivation clears `terminated_at` back to null. Note that this cooling-off rule is a minimum-gap-after-a-point-in-time buffer, distinct in kind from the lease-interval overlap rule described in §3.2 — the two should not be conflated even though both are temporal checks.

A `ComplianceOfficer` separately configures each state's rule via `state_code`, an optional `enrollment_allowed` (defaulting to true), a required `max_monthly_fee_pct_of_rent` (a fraction greater than 0 and at most 1), an optional `cooling_off_buffer_days` (defaulting to 30, and never negative), and an optional `mandatory_alternative_offering` (defaulting to true); each `state_code` may have only one configured rule, and submitting a `state_code` that already has one is rejected with `ERR_VALIDATION`. No property may accept a renter application in a state without a configured rule (§2.7), and the same rule's fee ceiling governs both the auto-approve and manual-approve underwriting paths described next.

### 3.2. Renter Application and Underwriting

A prospective tenant self-registers as a `Renter` with `full_name`, `email` (unique across renters), and `phone_number`. To apply for coverage in lieu of a cash deposit, the renter submits an enrollment against a specific unit: `property_id`, `renter_id`, a `payment_plan` of either `MONTHLY` or `ANNUAL_UPFRONT`, a `requested_coverage_limit_cents` (must be positive), `self_reported_annual_income_cents` (zero or greater), optionally `verified_annual_income_cents` and `employment_verified` (defaulting to false) when employer-side verification has already run, a `credit_proxy_score` between 300 and 850 inclusive, an optional `prior_eviction_count` (defaulting to 0, never negative), and the `lease_start_date`/`lease_end_date` pair the coverage is meant to span — `lease_end_date` must fall strictly after `lease_start_date`.

Three gates run before the application is even accepted, beyond the state-compliance checks in §2.7: the target property's `program_status` must be `ACTIVE`, or the request is rejected with `ERR_PROPERTY_NOT_ACTIVE` (HTTP 409); and the requested `[lease_start_date, lease_end_date)` window — treated as a half-open interval, so a lease ending exactly when another begins does not count as overlapping — must not overlap any existing non-terminal policy's lease window on the same property, or the request is rejected with `ERR_LEASE_TERM_OVERLAP` (HTTP 409). A new enrollment starts in `PENDING_UNDERWRITING`.

Submitting the enrollment for underwriting runs a weighted risk-scoring model. Three inputs feed it: the ratio of annual income to twelve times the property's `monthly_rent_cents`, the applicant's `credit_proxy_score`, and their `prior_eviction_count`. The income component is scored by dividing that income-to-rent ratio by a target ratio of 3.0, converting the result to a percentage, subtracting it from 100, and clamping the result between 0 and 100 — the further below the 3-times-rent income target the applicant falls, the higher this component. The credit component is scored by subtracting the applicant's `credit_proxy_score` from 850, dividing by the 550-point span between 850 and 300, converting to a percentage, and clamping between 0 and 100 — lower credit scores produce a higher risk contribution. The eviction component is 40 percentage points per prior eviction, capped at 100. The three components are then blended with fixed weights — 40% income, 40% credit, 20% eviction — and the blended figure is rounded half-up to a whole number to produce the final `risk_score`. A `risk_score` of 20 or below is classified `LOW`, 21 through 50 is `MEDIUM`, and 51 or above is `HIGH`; this classification is the `risk_tier`.

This score is computed twice under two variants that can legitimately diverge: the self-reported variant always runs, using `self_reported_annual_income_cents`, and is written to `risk_score_self_reported`; the verified variant runs only when `employment_verified` is true and `verified_annual_income_cents` has been supplied, using that verified figure instead, and is written to `risk_score_verified`. Both variants apply identically to the same `credit_proxy_score` and `prior_eviction_count` — only the income figure differs — so it is entirely possible for one variant to land in a different risk tier than the other for the same applicant. Whichever of the two is "official" for gating purposes is `risk_score_verified` when it exists, falling back to `risk_score_self_reported` otherwise; the resulting `risk_tier` field on the enrollment reflects whichever score is official.

Submission then forks on that official score. An official score of 35 (the auto-approve threshold) or below routes straight to `APPROVED`, provided the monthly fee that would result (computed exactly as described in §3.3, before any state-cap clamping) does not exceed the property's state fee ceiling — if it does, the submission is rejected with `ERR_FEE_EXCEEDS_STATE_CAP` (HTTP 422) rather than silently capping the fee. An official score above 35 routes instead to `MANUAL_REVIEW`, with no fee check at submission time. From `MANUAL_REVIEW`, an `UnderwritingAgent` issues a `decide` action of either `APPROVE` — subject to the identical fee-ceiling check, with the identical `ERR_FEE_EXCEEDS_STATE_CAP` rejection — or `DECLINE`, which moves the enrollment straight to the terminal `DECLINED` state with no policy created. Both the auto-approve path and the manual-approve path converge on the same side effect: a `Policy` is created — its `renter_enrollment_id` pointing back at the enrollment that produced it — with coverage limit seeded from `requested_coverage_limit_cents`, payment plan and lease dates copied across, monthly fee and both coverage-availability figures computed as described in §3.3, together with that policy's first `PremiumInvoice` (billing period beginning at the lease start date and running one month, due ten days after the billing period begins, its three monetary components computed as described in §3.3).

### 3.3. Policy Issuance and Premium Billing

A policy's monthly fee is driven by a tiered-pricing formula keyed off its risk tier. A risk multiplier is selected first — 1.0 for `LOW`, 1.3 for `MEDIUM`, 1.6 for `HIGH` — and multiplied against the coverage limit and against a base rate of 0.8% (expressed as the constant 0.008); that product is rounded half-up to the nearest cent, and a flat administrative fee of 150 cents is added on top to produce a pre-clamp figure. Separately, the state cap for the property is computed by multiplying the property's `monthly_rent_cents` by the governing `StateComplianceRule`'s `max_monthly_fee_pct_of_rent` and flooring to the nearest cent. If the pre-clamp figure exceeds that state cap, the operation that would have produced it is rejected outright with `ERR_FEE_EXCEEDS_STATE_CAP` — the fee is never silently reduced to fit. Only when the pre-clamp figure is within the cap does the final `monthly_fee_cents` get set, as the greater of the pre-clamp figure and a floor of 1,500 cents ($15). This same formula recomputes `monthly_fee_cents` on every subsequent coverage-limit adjustment, not just at policy creation.

Every `PremiumInvoice` — the first one issued at policy creation and every later one issued by the billing sweep — allocates the policy's current monthly fee across three components using a fixed waterfall, and the order of operations matters: each component is rounded to the nearest cent independently before the three are summed, never the other way around, because rounding the total once versus rounding each piece first can differ by a cent or two whenever a component lands exactly on a half-cent boundary. The `insurance_premium_cents` portion is 85% of the monthly fee, the `platform_fee_cents` portion is 10%, and the `state_tax_cents` portion is 5%, each rounded half-up; `amount_cents` is the sum of the three already-rounded components. Every invoice's `billing_period_start` and `billing_period_end` bound a one-month billing cycle (when adding a calendar month would overflow into a shorter month, the day-of-month is clamped to that month's last valid day), and its `due_date` is always ten days after `billing_period_start`.

Every date and deadline check in this system — including the overdue-grace comparison below and the re-enrollment cooldown in §3.1 — is measured against a server-side logical clock rather than real wall-clock time; a `PlatformAdmin` advances it by submitting a `to_iso8601` timestamp, and until the first such call the clock reads a fixed default of 2026-07-01T00:00:00Z.

A policy begins life `AWAITING_FIRST_PAYMENT`. Paying that first invoice — via a renter-initiated payment naming the invoice — transitions the policy to `ACTIVE`; the invoice itself moves from `ISSUED` to `PAID` and records `paid_at`. From then on, the platform's billing sweep drives the ongoing cycle: for every `ISSUED` invoice whose due date plus a five-day grace period (`OVERDUE_GRACE_DAYS`) has passed by the current logical clock time, the sweep marks it `OVERDUE` and, because that invoice belongs to an `ACTIVE` policy, cascades the policy to `LAPSED` in the same pass. A `LAPSED` policy is reinstated to `ACTIVE` the moment its renter pays the outstanding `OVERDUE` invoice — this is a genuine reinstatement cycle, `LAPSED` back to `ACTIVE`, not a one-way lapse. Separately, whenever an `ACTIVE` or `LAPSED` policy's current invoice has been paid and its next billing period has arrived, the sweep issues the next `PremiumInvoice` using the same three-component allocation described above; and whenever an `ACTIVE` or `LAPSED` policy's `lease_end_date` has passed, the sweep transitions it to the terminal `EXPIRED` state regardless of invoice status. `EXPIRED` and `CANCELLED` (§3.4) are the policy's only terminal states.

An `UnderwritingAgent` may adjust a live policy's coverage limit by submitting `requested_coverage_limit_cents` together with `expected_policy_version` (the OCC guard described in §2.4). A successful adjustment sets `coverage_limit_cents` to the requested value, recomputes `monthly_fee_cents` (subject to the same state-cap rejection described above), recomputes both `gross_available_coverage_cents` and `net_available_coverage_cents`, and increments the policy's `version` by one.

### 3.4. Cancellation and Move-Out

A `Renter` may cancel their own policy at any point while it is `ACTIVE` or `LAPSED` — both non-terminal states permit cancellation directly, without first requiring reinstatement. Cancelling records the current clock time as `cancelled_at` and moves the policy to the terminal `CANCELLED` state. A cancelled policy can no longer receive claims against it in good standing: the claims workflow in §3.5 explicitly checks that a claim's policy has not reached `CANCELLED` before allowing approval, since a cancelled relationship should not generate new payout obligations.

### 3.5. Claims Intake and Adjudication

A `Landlord` files a claim against one of their properties' policies by submitting `policy_id`, a `claim_type` of `UNPAID_RENT`, `PROPERTY_DAMAGE`, or `BOTH`, and an optional `line_items` array of `{description, amount_cents}` entries — the array may be empty at filing time, deferring itemization to later. A new claim starts `UNDER_REVIEW`, and `total_claimed_amount_cents` is always the sum of the current `line_items[].amount_cents`.

From `UNDER_REVIEW`, a `ClaimsAdjuster` can request more information, which moves the claim to `NEEDS_INFO` and records the adjuster's note in `decision_notes`. The landlord then submits the requested information back — this is a revision loop, not a one-way branch — which returns the claim to `UNDER_REVIEW`, appending any newly supplied `line_items` to the existing array and recomputing `total_claimed_amount_cents` from the combined set. A claim can cycle through `UNDER_REVIEW` and `NEEDS_INFO` as many times as needed before a decision is reached.

Approving a claim (`UNDER_REVIEW` to `APPROVED`) is gated by three checks, and they are evaluated in a fixed order: first, `line_items` must be non-empty, or the attempt is rejected with `ERR_CLAIM_HAS_NO_LINE_ITEMS` (HTTP 422) — an empty array blocks approval even if it did not block filing; second, the claim's policy must not be `CANCELLED`, or the attempt is rejected with `ERR_INVALID_STATE`; third, the payout amount the claim would generate must not exceed the policy's current gross available coverage, or the attempt is rejected with `ERR_COVERAGE_LIMIT_EXCEEDED` (HTTP 422) — this comparison is made against the uncapped figure described in step three below (total claimed amount minus the step-two deductible, floored at zero, before that figure is capped at gross available coverage), since the already-capped `approved_amount_cents` can never itself exceed gross available coverage. The payout amount itself is computed by a three-step threshold formula. Step one computes a provisional payout: take the smaller of the total claimed amount and the policy's gross available coverage, then subtract a flat deductible of 5,000 cents ($50), floored at zero. Step two decides which deductible tier actually applies, and it is decided from that step-one provisional figure specifically — never from the final amount — comparing it against a high-tier threshold of 200,000 cents ($2,000): at or above that threshold, the deductible is 1.5 times the flat deductible (7,500 cents); below it, the deductible stays at the flat 5,000 cents. Step three computes the final `approved_amount_cents` by applying the step-two deductible to the total claimed amount directly (not to the step-one provisional figure), floored at zero and capped again at the policy's gross available coverage. The applied deductible from step two is stored as `deductible_cents`. On approval, the claim also records `reviewing_adjuster_id` as the deciding `ClaimsAdjuster`'s `X-User-ID`, a `Payout` is created in `PENDING` status carrying the approved amount, and the policy's gross available coverage is recomputed as described in §2.8.

Denial is the sibling branch out of `UNDER_REVIEW`: a `ClaimsAdjuster` denies with an optional `decision_notes`, moving the claim straight to the terminal `DENIED` state and likewise recording `reviewing_adjuster_id`. `DENIED` and `CLOSED` are the claim's only terminal states — `CLOSED` is reached only via the payout-disbursement bubble-up described in §2.9, never directly.

### 3.6. Payout Disbursement

A `Payout` is created automatically — never directly by a caller — the moment its claim is approved, starting in `PENDING` with its `amount_cents` copied from the claim's approved amount. A `ClaimsAdjuster` disburses a `PENDING` payout by supplying an `action`, and the segregation-of-duties check described in §2.9 runs first: the disbursing adjuster's `X-User-ID` must differ from the `reviewing_adjuster_id` recorded when the underlying claim was approved, or the attempt is rejected with `ERR_SOD_VIOLATION` before any money moves. A successful disbursement records `disbursing_adjuster_id` and `disbursed_at`, and triggers the full three-hop cascade into the policy's net available coverage, the property's paid-claims total, and the claim's closure, exactly as detailed in §2.9.

A `PlatformAdmin` — not the disbursing adjuster — can later reverse a `DISBURSED` payout, supplying an optional `reversal_reason` (for example, a fraud finding), which moves it to the terminal `REVERSED` state, records `reversed_at`, and restores both the policy's net available coverage and the property's paid-claims total to their pre-disbursement values as the compensating action described in §2.8. Reversal does not reopen the underlying claim, which remains `CLOSED`.

### 3.7. Subrogation and Recovery

When a landlord's `UNPAID_RENT` or `BOTH` claim has actually been paid out — meaning its payout has reached `DISBURSED`, not merely `APPROVED` — a `ComplianceOfficer` can open a subrogation case to pursue recovery directly from the renter, submitting `claim_id` and `original_demand_amount_cents` (must be positive). Attempting this before the claim's payout has actually disbursed is rejected with `ERR_SUBROGATION_REQUIRES_DISBURSED_PAYOUT` (HTTP 409). A new case starts `OPEN` with `outstanding_balance_cents` initialized equal to the original demand.

From `OPEN`, the compliance officer sends a formal demand, moving the case to `DEMAND_SENT` and recording `demand_sent_at`. The renter then repays the balance incrementally: each `RecoveryPayment` submits `subrogation_case_id` and a positive `amount_cents`, and the payment is rejected with `ERR_RECOVERY_PAYMENT_EXCEEDS_BALANCE` (HTTP 422) if it would exceed the case's current outstanding balance. Each accepted payment recomputes `outstanding_balance_cents` as the original demand minus the sum of every non-reversed, `SUCCEEDED` recovery payment on that case; when that recomputation reaches exactly zero, the case is automatically closed out as `PAID_IN_FULL` in the same operation — a system-driven bubble-up, not a separate call. Alternatively, from `DEMAND_SENT`, the compliance officer can write off the case directly, moving it to the terminal `WRITTEN_OFF` state without further payment. `PAID_IN_FULL` and `WRITTEN_OFF` are the case's only terminal states.

A `PlatformAdmin` may reverse an individual `SUCCEEDED` recovery payment (for example, on a bounced or charged-back payment), which moves that payment to `REVERSED`, records `reversed_at`, and restores the case's outstanding balance to reflect the reversed amount as described in §2.8 — and if the case had already reached `PAID_IN_FULL`, the reversal reverts it back to `DEMAND_SENT` since the balance is no longer fully satisfied.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; endpoints that read, list, or transition an existing resource return HTTP 200. Request/response payloads and side effects are not repeated here — refer to the §3 narrative for the complete behavior of each endpoint.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/landlords` | Self-register a landlord account. | Anonymous |
| GET | `/landlords/{id}` | Read a single landlord. | Landlord, ComplianceOfficer, PlatformAdmin |
| POST | `/renters` | Self-register a renter account. | Anonymous |
| POST | `/properties` | List a property/unit for the program. | Landlord |
| GET | `/properties/{id}` | Read a single property. | Landlord, UnderwritingAgent, ClaimsAdjuster, ComplianceOfficer, PlatformAdmin |
| GET | `/landlords/{id}/properties` | List properties owned by a landlord. | Landlord, ComplianceOfficer, PlatformAdmin |
| POST | `/properties/{id}/program-status` | Transition a property's program enrollment. | ComplianceOfficer |
| POST | `/renter-enrollments` | Apply for coverage on a unit. | Renter |
| GET | `/renter-enrollments` | Filtered list of enrollments (optional `property_id`/`renter_id` query filters). | Renter, UnderwritingAgent, Landlord, PlatformAdmin |
| GET | `/renter-enrollments/{id}` | Read a single enrollment. | Renter, UnderwritingAgent, Landlord, PlatformAdmin |
| POST | `/renter-enrollments/{id}/submit-underwriting` | Run underwriting and auto-route the enrollment. | Renter |
| POST | `/renter-enrollments/{id}/decide` | Approve or decline an application under manual review. | UnderwritingAgent |
| GET | `/renter-enrollments/{id}/policy` | Find the policy created for this enrollment. | Renter, UnderwritingAgent, Landlord, PlatformAdmin |
| GET | `/policies/{id}` | Read a single policy. | Renter, UnderwritingAgent, Landlord, ClaimsAdjuster, ComplianceOfficer, PlatformAdmin |
| POST | `/policies/{id}/cancel` | Cancel/move out of a policy. | Renter |
| POST | `/policies/{id}/coverage-limit-adjustments` | Adjust a live policy's coverage limit (OCC-protected). | UnderwritingAgent |
| GET | `/policies/{id}/invoices` | List a policy's invoices. | Renter, UnderwritingAgent, ClaimsAdjuster, PlatformAdmin |
| POST | `/invoices/{id}/pay` | Pay an invoice. | Renter |
| POST | `/_billing/run-cycle` | System billing sweep. | PlatformAdmin |
| POST | `/policies/{id}/claims` | File a claim against a policy. | Landlord |
| GET | `/claims/{id}` | Read a single claim. | Landlord, ClaimsAdjuster, ComplianceOfficer, PlatformAdmin, Renter |
| GET | `/policies/{id}/claims` | List a policy's claims. | Landlord, ClaimsAdjuster, PlatformAdmin, Renter |
| POST | `/claims/{id}/info-transition` | Request or submit additional claim information. | ClaimsAdjuster, Landlord |
| POST | `/claims/{id}/decide` | Approve or deny a claim under review. | ClaimsAdjuster |
| GET | `/claims/{id}/payouts` | List a claim's payouts. | Landlord, ClaimsAdjuster, PlatformAdmin |
| POST | `/payouts/{id}/transition` | Disburse a pending payout or reverse a disbursed one. | ClaimsAdjuster, PlatformAdmin |
| POST | `/claims/{id}/subrogation-cases` | Open a recovery case against the renter. | ComplianceOfficer |
| GET | `/claims/{id}/subrogation-cases` | List a claim's subrogation cases. | ComplianceOfficer, PlatformAdmin, Renter |
| GET | `/subrogation-cases/{id}` | Read a single subrogation case. | ComplianceOfficer, PlatformAdmin, Renter |
| POST | `/subrogation-cases/{id}/transition` | Send the formal demand or write off the case. | ComplianceOfficer |
| POST | `/subrogation-cases/{id}/recovery-payments` | Record a payment toward the outstanding balance. | Renter |
| GET | `/subrogation-cases/{id}/recovery-payments` | List a case's recovery payments. | Renter, ComplianceOfficer, PlatformAdmin |
| POST | `/recovery-payments/{id}/reverse` | Reverse a recovery payment. | PlatformAdmin |
| POST | `/state-compliance-rules` | Configure the compliance rule for a state. | ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Set the server's logical current time. | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 400 |
| ERR_LANDLORD_NOT_FOUND | 404 |
| ERR_RENTER_NOT_FOUND | 404 |
| ERR_PROPERTY_NOT_FOUND | 404 |
| ERR_RENTER_ENROLLMENT_NOT_FOUND | 404 |
| ERR_POLICY_NOT_FOUND | 404 |
| ERR_INVOICE_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_PAYOUT_NOT_FOUND | 404 |
| ERR_SUBROGATION_CASE_NOT_FOUND | 404 |
| ERR_RECOVERY_PAYMENT_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STATE_NOT_CONFIGURED | 422 |
| ERR_STATE_ENROLLMENT_PROHIBITED | 422 |
| ERR_PROPERTY_NOT_ACTIVE | 409 |
| ERR_LEASE_TERM_OVERLAP | 409 |
| ERR_REENROLLMENT_COOLDOWN_ACTIVE | 409 |
| ERR_FEE_EXCEEDS_STATE_CAP | 422 |
| ERR_COVERAGE_LIMIT_EXCEEDED | 422 |
| ERR_CLAIM_HAS_NO_LINE_ITEMS | 422 |
| ERR_SOD_VIOLATION | 403 |
| ERR_SUBROGATION_REQUIRES_DISBURSED_PAYOUT | 409 |
| ERR_RECOVERY_PAYMENT_EXCEEDS_BALANCE | 422 |
| ERR_STALE_POLICY_VERSION | 412 |
