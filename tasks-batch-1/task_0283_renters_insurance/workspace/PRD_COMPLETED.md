# Renters Insurance API — Product Requirements Document

## 1. Introduction

This document specifies the Renters Insurance API, a carrier-side system of record for the full lifecycle of a renters policy. The product exists because renters insurance braids together several otherwise-separate disciplines — coverage design, pricing, billing, and claims adjudication — and a renter's protection depends on all of them staying consistent with one another. A single policy carries three lines of coverage (personal property, liability, and loss-of-use), may schedule individually appraised high-value items, may name a landlord or property manager as an additional insured, and may be bundled with the policyholder's other policies to earn a multi-policy discount. Premiums are computed from coverage limits, scheduled-item values, a territory factor, and bundle eligibility; they are billed annually or in monthly installments.

The harder half of the system is what happens after issuance. Premiums fall overdue, policies lapse for nonpayment and can be reinstated inside a limited window, and policies can be cancelled with either a pro-rata or a short-rate refund. Claims are filed, reviewed, approved, denied, appealed, reversed, and finally paid, with each approval eroding the remaining limit on the coverage lines it draws against and each reversal restoring it. Personal-property losses settle either at replacement cost or at depreciated actual-cash value, depending on a valuation method frozen onto the claim at filing. Because two operator roles — underwriting and claims adjustment — touch overlapping data and must remain segregated for compliance, and because concurrent edits to a policy's premium basis must not silently overwrite one another, the API enforces strict role separation, optimistic concurrency, and immediate cross-entity reconciliation. The sections below define those rules so that an implementation built solely from this document behaves identically to the reference.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, conventions, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly three roles, spelled precisely as `Underwriter`, `Policyholder`, and `ClaimsAdjuster`. When an authenticated role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The three roles divide responsibility along clear lines. The `Underwriter` is a carrier operator who creates policyholders, bundles, and policies, manages coverage lines and scheduled items, issues, cancels, and reinstates policies, runs the billing sweep, and voids payments. The `ClaimsAdjuster` is a claims operator who starts review on a claim, approves, denies, appeals, reverses, and pays it. The `Policyholder` is the insured account holder who views their own policies, claims, and invoices, names additional insureds, files claims and adds claim items, and pays premium invoices.

Two of these roles are tied to identity differently. When `X-User-Role` is `Policyholder`, `X-User-ID` is the `id` of the acting `Policyholder` entity; ownership checks on any resource that references a `Policyholder` compare the resource's `policyholder_id` (directly, or through the owning policy's `policyholder_id`) to `X-User-ID`, so a policyholder reads only their own policies, claims, invoices, coverage lines, scheduled items, additional insureds, and payments. When `X-User-Role` is `Underwriter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

Beyond role permission, the claim-settlement path enforces a segregation-of-duties rule. The underwriting and claims-adjustment authorities are mutually exclusive on that path: the same `X-User-ID` that reviewed a claim may not also pay it. When a pay request is submitted by an actor barred from that step under segregation of duties, it is rejected with `ERR_SEGREGATION_OF_DUTIES`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A supplied `limit` or `offset` that is non-integer or outside its stated range is rejected with `ERR_INVALID_REQUEST`. Unless an endpoint states otherwise, every list is ordered by the resource's `created_at` timestamp in ascending order, with ties broken by server insertion order so the ordering is stable when records share a `created_at` millisecond. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every entity in this system carries a server-minted `id` formatted as a UUID — never with a type prefix — and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. All entities in this system additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed on every mutation of the resource, and `version` starts at `1` on creation and increments by one on every mutation. The `version` field is the basis for optimistic concurrency control described in §2.7. Whenever a derived field is recomputed as a side effect of some workflow — for instance a coverage line's `remaining_limit_cents` or an invoice's `balance_due_cents` — that recomputation is itself a mutation of the owning resource and therefore advances its `updated_at` and `version`.

### 2.5. Nested Resource Retrieval and Referential Integrity

Many resources are addressed through a path that names a parent and then a child collection — for example a policy and its coverage lines, scheduled items, additional insureds, claims, or invoices, or an invoice and its payments. The system validates the identifiers in such a path strictly left to right, and the first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier is examined. The same `ERR_NOT_FOUND` covers any single-resource fetch whose path identifier is unknown.

Foreign keys supplied in a request body are validated separately. When a body references another resource by `policyholder_id`, `bundle_id`, `policy_id`, `invoice_id`, `coverage_line_id`, or `scheduled_item_id`, and that target does not exist, the request is rejected with `ERR_FK_NOT_FOUND`. A malformed body — a missing required field, a value of the wrong type, or an invalid enumeration value — is rejected with `ERR_INVALID_REQUEST`.

### 2.6. Monetary Amounts, Precision, and Rounding

All monetary amounts in this system are integers denominated in whole cents — for example `deductible_cents`, `limit_cents`, `appraised_value_cents`, `annual_premium_cents`, `amount_cents`, and the various settlement and balance fields. Wherever a computation produces a fractional cent, the result is rounded half up to the nearest whole cent. Several calculations pin the exact point at which rounding occurs (for instance, rounding each claim item before the items are summed, or rounding each premium component before the components are added); those orderings are spelled out with the calculations themselves in §3 and must be followed exactly, because rounding at a different step yields a different total.

### 2.7. Optimistic Concurrency Control on Policy Edits

Two write operations on a policy are guarded by optimistic concurrency control, because both re-run the premium calculation and advance the policy's `version`, and a client operating on a stale view of the policy's premium basis must not be allowed to commit. Both operations require a non-optional `expected_policy_version` field in the request body, carrying the `version` the client last observed on the target `Policy`.

The first guarded operation is adding a scheduled item to a policy. A scheduled-item add must carry `expected_policy_version` equal to the target policy's current `version`. If another writer has advanced the policy's `version` since the client last read it, the add is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412), preventing the client from extending a premium basis it has not observed. The second guarded operation is adding a coverage line to a quoted policy. That add likewise must carry `expected_policy_version` matching the policy's current `version`; a writer still holding the prior version has a stale view of which coverage types already exist and is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412). No other endpoint takes a version field; only these two adds carry `expected_policy_version`.

### 2.8. Hierarchical Consistency and Cascades

A policy sits at the head of a hierarchy of coverage lines, scheduled items, additional insureds, claims, and premium invoices, and several policy-level transitions cascade into those children. When a policy lapses, its coverage lines, scheduled items, and in-flight claims are suspended; when it is reinstated, they are restored; when it is cancelled or expires, scheduled items and active additional insureds are removed and coverage lines are frozen. Each of these cascades is described in full alongside the workflow that triggers it in §3. Every cascade that mutates a child resource advances that child's `updated_at` and `version` just as a direct edit would, and any recomputation of a bundle's membership counters or a policy's premium is itself a versioned mutation of the affected resource.

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the same offending request always produces the same error. Authentication comes first: a missing or malformed header (`ERR_UNAUTHENTICATED`) is caught before anything else, then role permission (`ERR_FORBIDDEN`), then — on the claim-pay path only — the segregation-of-duties check (`ERR_SEGREGATION_OF_DUTIES`). Existence checks follow: path identifiers resolved left to right (`ERR_NOT_FOUND`), then body foreign keys (`ERR_FK_NOT_FOUND`), then body shape and types (`ERR_INVALID_REQUEST`). Only after all of those does the system evaluate state and business rules: whether the target is in a state from which the transition is defined (`ERR_INVALID_STATE`, or the editability variant `ERR_POLICY_NOT_EDITABLE`/`ERR_POLICY_NOT_ACTIVE`/`ERR_POLICY_NOT_BILLABLE` where a workflow names one), then the optimistic-concurrency check on the two version-guarded adds (`ERR_STALE_POLICY_VERSION`), and finally the operation-specific business constraints described throughout §3. Concretely, on the two OCC-guarded adds of §2.7 the editability state check fires first (`ERR_POLICY_NOT_EDITABLE`), then the version match (`ERR_STALE_POLICY_VERSION`), and only then the coverage-type uniqueness check (`ERR_DUPLICATE_COVERAGE_TYPE`). The practical consequence is that, for example, an unauthenticated request to an endpoint whose path is also invalid still fails with `ERR_UNAUTHENTICATED`, and a state error is never reported for a resource that does not exist.

## 3. Business Logic & Workflows

### 3.1. Policyholders, Bundles, and the Multi-Policy Discount

Everything begins with a `Policyholder`, created by an `Underwriter` from an `email` (the unique login email), a `full_name` (the account holder's legal name), and a `mailing_address`. A policyholder may then own a `Bundle` — a grouping of their policies that earns a discount once enough of them are in force. A bundle is created with the owning `policyholder_id` and a display `name` such as "Home+Auto". A bundle tracks two computed counters and a lifecycle status. Its `active_member_count` is the number of member policies whose status is either `ACTIVE` or `LAPSED`, and it is recomputed whenever a policy attaches to or detaches from the bundle and whenever a member policy changes status; a freshly created bundle starts at zero. Its `discount_active` flag is `true` exactly when `active_member_count` is at least the minimum bundle size of two members, and that flag is what enables the discount multiplier in pricing. A bundle's `status` is one of `FORMING`, `ACTIVE`, or `DISSOLVED`, beginning at `FORMING`.

The bundle's own lifecycle is driven entirely by the system rather than by an explicit operator call. While a bundle is `FORMING`, the moment its `active_member_count` reaches the two-member minimum — through a policy issue or attach that bubbles the count up — the bundle transitions `FORMING → ACTIVE`, sets `discount_active` to `true`, and as a cascade re-runs the premium calculation on every member policy, since each is now eligible for the discount multiplier. Conversely, while a bundle is `ACTIVE`, if its `active_member_count` drops below the two-member minimum — through a cancellation or detach that bubbles the count down — the bundle transitions `ACTIVE → DISSOLVED`, sets `discount_active` to `false`, and as a cascade re-runs the premium calculation on every remaining member policy, each of which now loses the discount multiplier. A bundle may be fetched or listed by an `Underwriter` or a `Policyholder`, the list being filterable by `policyholder_id`.

### 3.2. Building and Pricing a Quoted Policy

An `Underwriter` opens a policy in the `QUOTED` state. Policy creation takes the insured party's `policyholder_id`, an optional `bundle_id` (absent for a standalone policy), the `insured_address` of the rented dwelling, a `territory_code` that must be one of `HIGH`, `STANDARD`, or `LOW`, an `effective_date` marking the inclusive start of the coverage term, an `expiry_date` marking the exclusive end of the term, a `deductible_cents` that must be zero or greater, an optional `pp_valuation_method` of `RCV` or `ACV` (defaulting to `RCV`) that fixes the default personal-property valuation for this policy's claims, and an optional `billing_mode` of `ANNUAL` or `MONTHLY` (defaulting to `ANNUAL`). The term interval is half-open: it includes `effective_date` and excludes `expiry_date`. At creation the policy's `status` is `QUOTED`, and if a `bundle_id` was supplied the bundle's `active_member_count` is recomputed — though a `QUOTED` policy does not yet count as an active member.

While a policy is still `QUOTED`, the underwriter assembles its coverage. A coverage line is added with its `coverage_type` — one of `PERSONAL_PROPERTY`, `LIABILITY`, or `LOSS_OF_USE` — and a `limit_cents` that must be greater than zero, drawing from the owning `policy_id`. Adding a coverage line is permitted only while the policy is `QUOTED`; an attempt against any other status is rejected with `ERR_POLICY_NOT_EDITABLE`. Each coverage type may appear at most once per policy, so a second line of a type already present is rejected with `ERR_DUPLICATE_COVERAGE_TYPE`. As established in §2.7, the add must carry `expected_policy_version` matching the policy's current `version`, failing with `ERR_STALE_POLICY_VERSION` otherwise. A freshly created coverage line begins with `settled_cents` at zero, `remaining_limit_cents` equal to its `limit_cents`, and `status` `OPEN`; the meaning of those derived fields is developed in §3.6. Every successful coverage-line add re-runs the premium calculation to refresh the policy's `annual_premium_cents` and increments the policy's `version` by one.

High-value belongings are covered by scheduling them individually. A scheduled item is added under the owning `policy_id` with a `description` (such as "engagement ring"), an `appraised_value_cents` greater than zero that serves as the agreed value for both surcharge and settlement, and an optional `deductible_waived` flag that defaults to `true`. When `deductible_waived` is `true`, the policy deductible is not applied to a claim on that item. A scheduled item is editable while the policy is in either `QUOTED` or `ACTIVE` status; an add against any other status is rejected with `ERR_POLICY_NOT_EDITABLE`. Like the coverage-line add, scheduling an item is OCC-guarded on `expected_policy_version` (see §2.7), re-runs the premium calculation to refresh `annual_premium_cents`, and increments the policy's `version` by one. A scheduled item's `status` is `ACTIVE` on creation and may later become `SUSPENDED` or `REMOVED` as the policy's own lifecycle dictates.

A landlord or property manager is recorded as an additional insured on the policy by either an `Underwriter` or the `Policyholder`. Such a record draws from the owning `policy_id` and carries the `party_name` (the interested party's legal name), an optional `interest_type` of `LANDLORD` or `PROPERTY_MANAGER` (defaulting to `LANDLORD`), and a `notify_email` to which lapse and cancellation notices are sent. Its `status` is `ACTIVE` on creation and becomes `REMOVED` when the policy terminates.

The **premium calculation** runs at issue and again on every coverage-line add, scheduled-item add or removal, and bundle eligibility change. It works from a small set of inputs and a fixed base policy fee of 12000 cents. First it reads each coverage line's `limit_cents`: the personal-property limit, the liability limit, and the loss-of-use limit, each treated as zero if that line does not exist yet. It also sums `appraised_value_cents` across every scheduled item whose `status` is not `REMOVED`. The subtotal is the base policy fee plus four rounded components: the personal-property limit multiplied by the personal-property rate of 0.004, the liability limit multiplied by the liability rate of 0.0008, the loss-of-use limit multiplied by the loss-of-use rate of 0.0015, and the scheduled-item sum multiplied by the scheduled-item rate of 0.018 — each of these four products rounded half up to a whole cent before being added into the subtotal. The subtotal is then multiplied by two factors. The territory factor is 1.25 for `HIGH`, 1.00 for `STANDARD`, and 0.85 for `LOW`. The bundle factor is 0.90 when the policy's bundle has `discount_active` true, and 1.00 otherwise. The final `annual_premium_cents` is the subtotal multiplied by the territory factor and the bundle factor, with that single final product rounded half up to a whole cent. Note that `billing_mode` does not alter `annual_premium_cents` at all; it changes only the amount of the invoice created at issue, as described in §3.3.

### 3.3. Issuing a Policy and Establishing Billing

Issuing a policy advances it from `QUOTED` to `ACTIVE`, an `Underwriter`-only action. Three preconditions guard it. The policy must carry exactly one coverage line of each of the three coverage types `PERSONAL_PROPERTY`, `LIABILITY`, and `LOSS_OF_USE`; a policy missing any of them is rejected with `ERR_COVERAGE_INCOMPLETE`. The `effective_date` must be strictly earlier than the `expiry_date`, failing which the issue is rejected with `ERR_INVALID_TERM`. And the new term must not overlap the term of any other `ACTIVE` or `LAPSED` policy held by the same `policyholder_id`; because the term interval is half-open over `[effective_date, expiry_date)`, two terms that merely touch at a shared boundary instant do not overlap, but any genuine overlap is rejected with `ERR_TERM_OVERLAP`. The overlap guard excludes any other policy that shares this policy's own non-null `bundle_id`: two members of the same bundle are concurrent in-force coverage by design, so a candidate policy carrying a non-null `bundle_id` is checked for overlap only against policies that do not belong to that same bundle.

On a successful issue several things happen together. The premium calculation runs and sets `annual_premium_cents`. Exactly one `PremiumInvoice` is created for the policy, drawing from its `policy_id`, with its `due_date` set to the policy's `effective_date` and its `status` `OPEN`. The invoice's `amount_cents` depends on billing mode: for an `ANNUAL` policy it is the full `annual_premium_cents`, while for a `MONTHLY` policy it is one installment, computed as the annual premium multiplied by 1.05 and divided by 12, rounded half up to a whole cent — the 1.05 factor being the five-percent installment surcharge. At creation the invoice's `paid_cents` is zero and its `balance_due_cents` equals its `amount_cents`. Issue also sets every coverage line's `remaining_limit_cents` to its `limit_cents` with `status` `OPEN`. Finally, if the policy belongs to a bundle, the bundle's `active_member_count` and `discount_active` are recomputed, which may bubble the bundle up to `ACTIVE` per §3.1.

A `PremiumInvoice` carries a `status` of `OPEN`, `PAID`, or `OVERDUE`, and its `balance_due_cents` is always its `amount_cents` minus its `paid_cents`, where `paid_cents` is the sum of all cleared payments against it. Invoices may be fetched or listed (filterable by `policy_id` and `status`) by an `Underwriter` or `Policyholder`.

### 3.4. Premium Payments, Voids, and the Billing Sweep

A payment is recorded against an invoice by a `Policyholder` or an `Underwriter`. The payment draws from the `invoice_id` it pays, an `amount_cents` greater than zero, and an optional `method` of `CARD`, `ACH`, or `CHECK` (defaulting to `CARD`); a recorded payment's `status` is `CLEARED`. A payment may be recorded only while the owning policy's status is `ACTIVE` or `LAPSED`; against a policy in any other status the payment is rejected with `ERR_POLICY_NOT_BILLABLE`. Recording a cleared payment recomputes the invoice's `paid_cents` and `balance_due_cents`, and when the resulting `balance_due_cents` reaches zero the invoice moves to `PAID`. An invoice that was `OPEN` and is paid in full transitions `OPEN → PAID`; an invoice that had gone `OVERDUE` and is then paid down to a zero balance — which is how a lapsed policy clears its overdue premium ahead of reinstatement — likewise transitions `OVERDUE → PAID`, and that overdue-payment path requires the owning policy to be `LAPSED` (otherwise `ERR_POLICY_NOT_BILLABLE`).

A cleared payment may be voided by an `Underwriter`. Voiding is allowed only on a payment whose `status` is `CLEARED`; a payment that is already voided cannot be voided again and is rejected with `ERR_PAYMENT_NOT_VOIDABLE`. Voiding sets the payment's `status` to `VOIDED` and recomputes the invoice's `paid_cents` and `balance_due_cents` so that the balance returns to `amount_cents` minus the sum of the remaining cleared payments — money is conserved. If that recomputation leaves `balance_due_cents` greater than zero, an invoice that had been `PAID` reopens, transitioning `PAID → OPEN`.

A grace period and a billing sweep convert missed payments into lapses. An `Underwriter` runs the sweep against a single policy, which must be `ACTIVE` (a sweep against a policy in any other status is rejected with `ERR_INVALID_STATE`), and the sweep evaluates that policy against the server's current clock for two possible outcomes, considered in a fixed order: expiry is evaluated first, then lapse. For an expiry, the current clock must have reached or passed the policy's `expiry_date`; when it has, the policy transitions `ACTIVE → EXPIRED` and the sweep returns without evaluating lapse. For a lapse — reached only when the clock has not yet passed `expiry_date` — there must be an `OPEN` or `OVERDUE` invoice whose `balance_due_cents` is greater than zero — if none exists the sweep is rejected with `ERR_NO_OVERDUE_INVOICE` — and the current clock must have reached or passed that invoice's `due_date` plus the grace period of fourteen days; if the clock has not yet reached that point the sweep is rejected with `ERR_NOT_YET_LAPSABLE`. When both conditions hold the policy transitions `ACTIVE → LAPSED`. If neither outcome applies — the clock has not reached `expiry_date` and there is no `OPEN`/`OVERDUE` invoice with a positive balance to lapse — the sweep is rejected with `ERR_NOT_YET_EXPIRED`; under this ordering the absence of a lapsable invoice on a not-yet-expired policy surfaces as `ERR_NOT_YET_EXPIRED` rather than `ERR_NO_OVERDUE_INVOICE`. The server's clock used for all grace, lapse, expiry, reinstatement-window, and refund timing can be set directly through an `Underwriter`-only test-driving capability that accepts a target instant in the `to_iso8601` field and reports back the `current_utc` it set.

When a policy lapses, several effects fire as one cascade. Its `lapse_reason` is set to `NONPAYMENT`. The overdue invoice's `status` is set to `OVERDUE`. Every coverage line currently `OPEN` or `EXHAUSTED` is set to `SUSPENDED`; every scheduled item currently `ACTIVE` is set to `SUSPENDED`; and every claim currently in `FILED`, `UNDER_REVIEW`, or `APPROVED` is set to `SUSPENDED`. A lapsed policy still counts toward its bundle's `active_member_count`, so the bundle membership and discount are unaffected by a lapse. When a policy expires, its coverage lines are frozen in their terminal status, every scheduled item is set to `REMOVED`, and every `ACTIVE` additional insured is set to `REMOVED`.

### 3.5. Lapse Recovery: Reinstatement, Cancellation, and Refunds

A `LAPSED` policy can be brought back to `ACTIVE` through reinstatement by an `Underwriter`, but only inside a closing window and only once its arrears are settled. Three preconditions apply, each with its own rejection. The overdue invoice must be fully paid, meaning its `balance_due_cents` is zero; otherwise the reinstatement is rejected with `ERR_LAPSE_BALANCE_OUTSTANDING`. The reinstatement fee must have been paid — satisfied either by a separate zero-balance premium invoice on the same policy other than the overdue invoice cleared by the balance precondition above, or by the request body setting `reinstatement_fee_paid` to `true`; if the fee is unpaid the request is rejected with `ERR_REINSTATE_FEE_UNPAID`. And the current clock must be no later than the overdue invoice's `due_date` plus the fourteen-day grace period plus the reinstatement window of thirty additional days; once that combined window has passed the request is rejected with `ERR_REINSTATE_WINDOW_CLOSED`.

A successful reinstatement transitions the policy `LAPSED → ACTIVE` and reverses the lapse cascade. It clears `lapse_reason` back to null, increments `reinstatement_count` by one, and sets the formerly overdue invoice's `status` to `PAID`. Each suspended coverage line is restored: to `OPEN` if its `remaining_limit_cents` is greater than zero, or to `EXHAUSTED` if its `remaining_limit_cents` is zero. Each suspended scheduled item is restored to `ACTIVE`. Each suspended claim is restored to whichever status it held before suspension — `FILED`, `UNDER_REVIEW`, or `APPROVED`.

Cancellation, also an `Underwriter` action, ends a policy early with a refund, moving it to the terminal `CANCELLED` status. A policy can be cancelled from `ACTIVE` or from `LAPSED`. From `ACTIVE`, cancellation is blocked while any claim is in `FILED`, `UNDER_REVIEW`, or `APPROVED`, and such an attempt is rejected with `ERR_OPEN_CLAIM_BLOCKS_CANCEL`. From `LAPSED`, cancellation is blocked while any claim is in `FILED`, `UNDER_REVIEW`, `APPROVED`, or `SUSPENDED`, again rejected with `ERR_OPEN_CLAIM_BLOCKS_CANCEL`. The cancel request supplies the desired `refund_method`. Cancelling an `ACTIVE` policy runs the **cancellation refund** using that method and records the result in `refund_method` and `refund_amount_cents`; it freezes every coverage line's status as terminal, sets every scheduled item to `REMOVED`, and sets every `ACTIVE` additional insured to `REMOVED` so the landlord receives termination notice. If the policy is bundled, its bundle's `active_member_count` and `discount_active` are recomputed, which may bubble the bundle down and dissolve it per §3.1. Cancelling a `LAPSED` policy instead records `refund_method` as requested but sets `refund_amount_cents` to zero, because a lapsed policy forfeits its refund; if bundled, the bundle counters are still recomputed.

The **cancellation refund** is computed from the policy's dates, the cancel-time clock, and the premium actually paid. The term length in whole days is the `expiry_date` minus the `effective_date`. The elapsed length is the cancel-time clock minus the `effective_date` in whole days, clamped so that it is never below zero and never above the term length. The unused length is the term length minus the elapsed length. The paid premium is the sum of `amount_cents` across all cleared payments on the policy's invoices. The pro-rata refund is the paid premium multiplied by the unused days and divided by the term days, rounded half up to a whole cent. If the requested `refund_method` is `PRO_RATA`, the `refund_amount_cents` is exactly that pro-rata refund. If the requested method is `SHORT_RATE`, a penalty equal to the paid premium multiplied by the short-rate penalty of ten percent (rounded half up to a whole cent) is subtracted from the pro-rata refund, and `refund_amount_cents` is the larger of zero and that difference — so for the same inputs a short-rate refund is strictly less than a pro-rata refund.

### 3.6. Coverage Limits and the Settlement Ledger

Each coverage line maintains a running ledger of how much of its limit a claim term has consumed. Its `settled_cents` is the cumulative settlement of approved claims debited against the line during the term, and its `remaining_limit_cents` is its `limit_cents` minus its `settled_cents`, never dropping below zero. A line's `status` is `OPEN` while limit remains, `EXHAUSTED` once `remaining_limit_cents` reaches zero, and `SUSPENDED` while its policy is lapsed. A standing invariant ties these together: for every coverage line, its `limit_cents` always equals its `remaining_limit_cents` plus its `settled_cents`. Coverage lines and scheduled items of a policy can be listed by an `Underwriter` or the owning `Policyholder`.

The ledger moves only when a claim is approved or an approval is reversed, and it allocates a claim's settlement across the coverage lines its items reference using a deterministic waterfall. The referenced lines are processed in ascending `created_at` order — never by `id` — and each line is filled up to its `remaining_limit_cents` in turn: the share assigned to a line is the smaller of the still-unallocated settlement and that line's `remaining_limit_cents`. On approval, that share is added to the line's `settled_cents`; on a reversal, the prior share is subtracted back out. After each adjustment the line's `remaining_limit_cents` is recomputed as `limit_cents` minus `settled_cents`, and the line is marked `EXHAUSTED` if its remaining limit is zero or `OPEN` if it is greater than zero. This allocation is exact integer arithmetic with no rounding.

### 3.7. Filing a Claim and Adding Items

A claim is filed under an `ACTIVE` policy by an `Underwriter` or a `Policyholder`. Filing requires the owning policy to be `ACTIVE`; against a policy in any other status the filing is rejected with `ERR_POLICY_NOT_ACTIVE`. The claim draws from the owning `policy_id` and carries a `loss_type` of `PERSONAL_PROPERTY`, `LIABILITY`, or `LOSS_OF_USE`, and a `loss_date`. The `loss_date` must fall within the owning policy's half-open term `[effective_date, expiry_date)`; a loss dated outside the term is rejected with `ERR_LOSS_OUTSIDE_TERM`. For a `LOSS_OF_USE` claim the filing may also carry a `displacement_start` and a `displacement_end` describing the displacement interval as a closed interval inclusive of both endpoints; both fields are optional (a `LOSS_OF_USE` claim filed without them is accepted), and the overlap check below runs only when both are supplied. When supplied, this interval must neither overlap nor share a boundary instant with the displacement interval of any existing non-terminal `LOSS_OF_USE` claim on the same policy — where only a `SETTLED` `LOSS_OF_USE` claim (and any whose own displacement endpoints are absent) is treated as terminal and thus exempt from blocking, so a `DENIED` or `SUSPENDED` `LOSS_OF_USE` claim still blocks — and any such collision — including one that merely touches at a shared endpoint — is rejected with `ERR_DISPLACEMENT_OVERLAP`. At filing, a `PERSONAL_PROPERTY` claim has its `valuation_method` frozen from the policy's `pp_valuation_method` to either `RCV` or `ACV`; liability and loss-of-use claims always settle at the full claimed amount (an RCV-equivalent basis). A new claim's `status` is `FILED`, its `appeal_count` is zero, and its computed amounts — `covered_loss_cents`, `deductible_applied_cents`, and `settlement_cents` — start at zero. A `denial_reason` is recorded only when an adjuster later denies or reverses the claim.

A claim accumulates line items while it is still `FILED`. A claim item is added by an `Underwriter` or a `Policyholder`, drawing from the owning `claim_id` and the `coverage_line_id` of the base coverage line it draws against, plus an optional `scheduled_item_id` set when the item is a scheduled high-value rider. The item also carries a `replacement_cost_cents` greater than zero (the cost to replace new, the RCV basis), an optional `age_months` defaulting to zero, and an optional `useful_life_months` defaulting to 60 and required to be greater than zero, both of which feed depreciation under ACV. The referenced coverage line's `coverage_type` must match the claim's `loss_type`; a mismatch is rejected with `ERR_COVERAGE_TYPE_MISMATCH`. Each item's computed `covered_item_cents` — its covered amount under the claim's frozen valuation method, rounded to whole cents — is established when the claim is reviewed, as described in §3.8. Claims and claim items can be read by an `Underwriter`, a `Policyholder`, or a `ClaimsAdjuster`; claims list filterably by `policy_id` and `status`, and claim items list filterably by `claim_id`, `coverage_line_id`, and `scheduled_item_id`.

### 3.8. Claim Review, Settlement, and the Adjudication Loop

The claims path is the province of the `ClaimsAdjuster`. Starting review advances a claim `FILED → UNDER_REVIEW`. It requires the owning policy to be `ACTIVE` (else `ERR_POLICY_NOT_ACTIVE`) and the claim to have at least one claim item (else `ERR_CLAIM_EMPTY`). Starting review runs the **claim settlement** in provisional mode, populating `covered_loss_cents`, `deductible_applied_cents`, and `settlement_cents` without yet debiting any coverage line.

The **claim settlement** computes the payout from the claim's items, the frozen `valuation_method`, the referenced coverage lines' remaining limits read at calculation time, and the policy deductible. For each claim item the covered amount is determined first. When the claim's `valuation_method` is `ACV` and the loss is `PERSONAL_PROPERTY`, the item depreciates: its depreciation fraction is the smaller of its `age_months` divided by its `useful_life_months` and the maximum depreciation of 0.80, and its `covered_item_cents` is the `replacement_cost_cents` multiplied by one minus that depreciation fraction, rounded half up to a whole cent. Otherwise — under `RCV`, or for any liability or loss-of-use loss — the item's `covered_item_cents` is its full `replacement_cost_cents` with no depreciation. The rounding order is pinned: each item is rounded to whole cents first, and only then are the items summed, so that `covered_loss_cents` is the sum of the already-rounded per-item amounts. The deductible is applied next. The waived portion is the sum of `covered_item_cents` over those items whose referenced scheduled item has `deductible_waived` true; the deductible-eligible amount is `covered_loss_cents` minus that waived portion; and `deductible_applied_cents` is the smaller of the policy's `deductible_cents` and that eligible amount — so when only deductible-waived scheduled items are claimed, the applied deductible is zero. Finally the limit cap is applied: the capped loss is the smaller of `covered_loss_cents` and the sum of `remaining_limit_cents` across the referenced coverage lines, and `settlement_cents` is the larger of zero and the capped loss minus `deductible_applied_cents`. Under identical inputs an ACV claim yields a strictly lower payout than an RCV claim.

From `UNDER_REVIEW` the adjuster has two forward moves. Approving advances `UNDER_REVIEW → APPROVED`. It requires the owning policy to be `ACTIVE` (else `ERR_POLICY_NOT_ACTIVE`) and requires that `settlement_cents` not exceed the sum of `remaining_limit_cents` across the referenced coverage lines (else `ERR_LIMIT_EXCEEDED`). On approval the claim settlement re-runs in final mode to recompute `settlement_cents`, and the settlement ledger debits each referenced coverage line by its waterfall share per §3.6, recomputing each line's `remaining_limit_cents` and flipping any fully consumed line to `EXHAUSTED`. Denying instead advances `UNDER_REVIEW → DENIED`; it requires a `denial_reason` (else `ERR_DENIAL_REASON_REQUIRED`) and sets `settlement_cents` to zero with no coverage-line debit.

The adjudication loop lets a denied claim be revisited. Appealing advances `DENIED → UNDER_REVIEW`. It requires the owning policy to be `ACTIVE` (else `ERR_POLICY_NOT_ACTIVE`) and requires that `appeal_count` be below the maximum of two appeals (else `ERR_APPEAL_LIMIT_REACHED`). A successful appeal increments `appeal_count` by one, clears the `denial_reason`, and re-runs the claim settlement in provisional mode. Symmetrically, an approval can be unwound: reversing an approval advances `APPROVED → DENIED`, requires a `denial_reason` (else `ERR_DENIAL_REASON_REQUIRED`), and as a compensation credits back each referenced coverage line by the share it was previously debited — recomputing each line's `remaining_limit_cents` and restoring a line to `OPEN` whenever its remaining limit becomes greater than zero — then sets `settlement_cents` to zero. The final forward move is payment: paying a claim advances `APPROVED → SETTLED` and requires the owning policy to be `ACTIVE` (else `ERR_POLICY_NOT_ACTIVE`); the coverage-line debits applied at approval remain in place, and the settlement is marked disbursed. Payment is additionally subject to the segregation-of-duties rule of §2.1: the same `X-User-ID` may not both review and pay one claim — where "reviewed" identifies the actor who performed `start-review` (the reviewer recorded at the original `FILED → UNDER_REVIEW` transition and not re-stamped by a later appeal) — and a barred actor's pay request fails with `ERR_SEGREGATION_OF_DUTIES`. A claim reaches one of these states from the set `FILED`, `UNDER_REVIEW`, `APPROVED`, `DENIED`, `SETTLED`, or `SUSPENDED`, and any transition requested from a state where it is not defined is rejected with `ERR_INVALID_STATE`. On the four transitions that carry an `ACTIVE`-policy precondition — `start-review`, `approve`, `appeal`, and `pay` — that cross-entity policy-state check is evaluated before the claim's own state check, so a claim that a lapse has driven to `SUSPENDED` (its owning policy now `LAPSED`) surfaces `ERR_POLICY_NOT_ACTIVE` rather than `ERR_INVALID_STATE`; on `pay` the segregation-of-duties check still precedes the policy-state check.

## 4. Endpoint Definitions

Operations that create a new resource — a policyholder, a bundle, a policy, a coverage line, a scheduled item, an additional insured, a claim, a claim item, or a payment — return `201 Created`. Operations that modify an existing resource, including every state-transition action on a policy, claim, invoice, or payment, return `200 OK`. The request body, response body, and side effects of each endpoint are not repeated here; reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/policyholders` | Create a policyholder account | Underwriter |
| GET | `/policyholders/{id}` | Fetch a policyholder | Underwriter, Policyholder |
| GET | `/policyholders` | List policyholders (filter by email) | Underwriter |
| POST | `/bundles` | Create a multi-policy bundle | Underwriter |
| GET | `/bundles/{id}` | Fetch a bundle | Underwriter, Policyholder |
| GET | `/bundles` | List bundles (filter by policyholder_id) | Underwriter, Policyholder |
| POST | `/policies` | Create a QUOTED policy | Underwriter |
| GET | `/policies/{id}` | Fetch a policy with computed premium and status | Underwriter, Policyholder |
| GET | `/policies` | List policies (filter by policyholder_id, bundle_id, status) | Underwriter, Policyholder |
| POST | `/policies/{id}/coverage-lines` | Add a coverage line to a QUOTED policy (OCC-guarded) | Underwriter |
| GET | `/policies/{id}/coverage-lines` | List coverage lines of a policy | Underwriter, Policyholder |
| POST | `/policies/{id}/scheduled-items` | Schedule a high-value item (OCC-guarded) | Underwriter |
| GET | `/policies/{id}/scheduled-items` | List scheduled items of a policy | Underwriter, Policyholder |
| POST | `/policies/{id}/additional-insureds` | Name an additional insured on the policy | Underwriter, Policyholder |
| GET | `/policies/{id}/additional-insureds` | List additional insureds of a policy | Underwriter, Policyholder |
| POST | `/policies/{id}/issue` | Issue (activate) a QUOTED policy | Underwriter |
| POST | `/policies/{id}/cancel` | Cancel an ACTIVE or LAPSED policy with a refund method | Underwriter |
| POST | `/policies/{id}/reinstate` | Reinstate a LAPSED policy | Underwriter |
| POST | `/policies/{id}/process-billing` | Billing sweep: evaluate the policy for lapse or expiry | Underwriter |
| POST | `/policies/{id}/claims` | File a claim under an ACTIVE policy | Underwriter, Policyholder |
| GET | `/claims/{id}` | Fetch a claim with computed settlement fields | Underwriter, Policyholder, ClaimsAdjuster |
| GET | `/claims` | List claims (filter by policy_id, status) | Underwriter, Policyholder, ClaimsAdjuster |
| POST | `/claims/{id}/items` | Add a claim line item (FILED claims only) | Underwriter, Policyholder |
| GET | `/claim-items/{id}` | Fetch a single claim line item | Underwriter, Policyholder, ClaimsAdjuster |
| GET | `/claim-items` | List claim line items (filter by claim_id, coverage_line_id, scheduled_item_id) | Underwriter, Policyholder, ClaimsAdjuster |
| POST | `/claims/{id}/start-review` | Move claim FILED→UNDER_REVIEW; provisional settlement | ClaimsAdjuster |
| POST | `/claims/{id}/approve` | Approve claim UNDER_REVIEW→APPROVED; debit coverage limits | ClaimsAdjuster |
| POST | `/claims/{id}/deny` | Deny claim UNDER_REVIEW→DENIED | ClaimsAdjuster |
| POST | `/claims/{id}/appeal` | Appeal a DENIED claim back to UNDER_REVIEW | ClaimsAdjuster |
| POST | `/claims/{id}/reverse-approval` | Reverse an APPROVED claim to DENIED; credit limits back | ClaimsAdjuster |
| POST | `/claims/{id}/pay` | Disburse an APPROVED claim, moving it to SETTLED | ClaimsAdjuster |
| GET | `/premium-invoices/{id}` | Fetch a premium invoice with derived balance | Underwriter, Policyholder |
| GET | `/premium-invoices` | List premium invoices (filter by policy_id, status) | Underwriter, Policyholder |
| POST | `/premium-invoices/{id}/payments` | Record a payment against an invoice | Policyholder, Underwriter |
| GET | `/premium-invoices/{id}/payments` | List payments of an invoice | Underwriter, Policyholder |
| GET | `/payments` | List payments (filter by invoice_id) | Underwriter, Policyholder |
| POST | `/payments/{id}/void` | Void a CLEARED payment; recompute invoice balance | Underwriter |
| POST | `/_clock/set_current_utc` | Test hook: set the server's current UTC clock | Underwriter |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_POLICY_NOT_EDITABLE` | 409 |
| `ERR_POLICY_NOT_ACTIVE` | 409 |
| `ERR_POLICY_NOT_BILLABLE` | 409 |
| `ERR_STALE_POLICY_VERSION` | 412 |
| `ERR_DUPLICATE_COVERAGE_TYPE` | 409 |
| `ERR_COVERAGE_INCOMPLETE` | 422 |
| `ERR_INVALID_TERM` | 422 |
| `ERR_TERM_OVERLAP` | 409 |
| `ERR_LOSS_OUTSIDE_TERM` | 422 |
| `ERR_DISPLACEMENT_OVERLAP` | 409 |
| `ERR_COVERAGE_TYPE_MISMATCH` | 422 |
| `ERR_CLAIM_EMPTY` | 422 |
| `ERR_LIMIT_EXCEEDED` | 422 |
| `ERR_DENIAL_REASON_REQUIRED` | 422 |
| `ERR_APPEAL_LIMIT_REACHED` | 409 |
| `ERR_OPEN_CLAIM_BLOCKS_CANCEL` | 409 |
| `ERR_NO_OVERDUE_INVOICE` | 409 |
| `ERR_NOT_YET_LAPSABLE` | 409 |
| `ERR_NOT_YET_EXPIRED` | 409 |
| `ERR_LAPSE_BALANCE_OUTSTANDING` | 409 |
| `ERR_REINSTATE_FEE_UNPAID` | 402 |
| `ERR_REINSTATE_WINDOW_CLOSED` | 409 |
| `ERR_PAYMENT_NOT_VOIDABLE` | 409 |
