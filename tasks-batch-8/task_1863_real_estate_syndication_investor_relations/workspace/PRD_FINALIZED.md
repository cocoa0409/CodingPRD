# Real Estate Syndication & Investor Relations API — Product Requirements Document

## 1. Introduction

Real estate syndicators operate under an unusual combination of pressures: they raise capital from dozens of limited partners under securities law, they owe those partners audited waterfall distributions calculated to the cent, and they must keep a paper trail that can survive an SEC examination years later. A missed accreditation check, a misapplied preferred-return accrual, or a K-1 package that drifts a few cents from the partnership's reported NOI is not a cosmetic bug — it is a compliance finding. This document specifies the API surface of a syndication management platform designed for that environment. It covers the full lifecycle of a deal: structuring an offering under a sponsor entity, collecting and reviewing subscription documents, verifying investor accreditation and suitability under segregation of duties, calling capital into escrow and releasing it against due dates, publishing quarterly performance reports, running multi-tier distribution waterfalls, coordinating K-1 tax packages with an external preparer, executing capital events such as refinances and sales, and processing investor-initiated transfer requests through sponsor and transfer-agent review.

Four actor types interact with the platform. A sponsor's operations staff drafts and runs deals; an independent compliance desk verifies accreditation and suitability, deliberately separated from the sponsor's write path; a transfer agent clears secondary-market transfers between investors; and investors themselves self-serve through a portal to submit subscriptions, upload documents, wire escrow payments, and read their positions. Because so many workflows are time-dependent — preferred returns accrue per elapsed quarter, accreditation letters expire, escrow receipts face due dates, and reports may not be filed for future periods — the platform exposes a logical-clock capability so operators and tests can deterministically advance time. All monetary values are integer cents, and every computed amount in the system rounds half-up to zero decimal places, with no exceptions.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the named role is not permitted to invoke the endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Four roles exist, with these exact spellings: `SponsorOperator`, `ComplianceOfficer`, `TransferAgent`, and `Investor`.

When `X-User-Role` is `SponsorOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same holds when `X-User-Role` is `ComplianceOfficer` — the identifier is opaque, though the server does record it as `accreditation_verified_by` and `suitability_verified_by` on the subscriptions that officer acts upon — and when `X-User-Role` is `TransferAgent`, where the identifier is likewise opaque and never matched against a stored record. When `X-User-Role` is `Investor`, `X-User-ID` is the `id` of the acting `Investor`; ownership checks on any resource that references an `Investor` compare the resource's foreign-key field to `X-User-ID`. This binding is what lets the platform reject one investor wiring escrow against another investor's contribution, or cancelling another investor's transfer request.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0. Results are always sorted by `created_at` ascending. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` envelope.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix. Resources that participate in the full lifecycle model additionally carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps rendered with three fractional digits, and an integer `version` that increments by one on every mutation of that resource. Two resource kinds are deliberately lighter: `SubscriptionDocument` and `DistributionLine` carry only `id` and `created_at`; they have neither `updated_at` nor `version`, since documents are immutable once uploaded (their `review_status` flips in place via the review workflow) and distribution lines are discarded and regenerated rather than edited.

### 2.5. Nested Path Resolution

The API is deeply nested: an offering lives under a syndication, a subscription under an offering, a document or transfer request under a subscription, a contribution under a capital call, and so on. The URL path variables are, in hierarchy order, `syndicationId`, `offeringId`, `subscriptionId`, `documentId`, `transferRequestId`, `capitalCallId`, `contributionId`, `quarterlyReportId`, `distributionId`, `lineId`, `k1PackageId`, plus the peer-level `investorId`, `propertyId`, `capitalEventId`, and `sessionId`. Path parameters are validated left to right — the syndication first, then the offering, then the subscription, then any deeper child identifier. A failure at any step yields the corresponding not-found error: `ERR_SYNDICATION_NOT_FOUND`, `ERR_OFFERING_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_INVESTOR_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_CAPITAL_CALL_NOT_FOUND`, `ERR_CONTRIBUTION_NOT_FOUND`, `ERR_QUARTERLY_REPORT_NOT_FOUND`, `ERR_DISTRIBUTION_NOT_FOUND`, `ERR_CAPITAL_EVENT_NOT_FOUND`, `ERR_K1_PACKAGE_NOT_FOUND`, or `ERR_TRANSFER_REQUEST_NOT_FOUND`, each with HTTP 404. A child identifier that exists but not beneath the named parent is treated as not found, not as a permission failure. Alongside the nested routes, the platform also exposes flat filtered-list reads (for example, listing all offerings across syndications filtered by `property_id`, or all subscriptions filtered by `investor_id`) so that back-office tools can resolve children from a foreign key without walking the full hierarchy; these flat reads accept the same pagination parameters and the documented filter parameters for each resource.

### 2.6. Monetary Representation, Precision, and Rounding

All money in the platform is represented as integer cents: `committed_cents`, `funded_cents`, `total_call_cents`, `amount_due_cents`, `gross_proceeds_cents`, and their kin are integers, never floats. Every computed monetary value is rounded half-up to zero decimal places at the point it is produced. Two different reconciliation disciplines appear in the calculations below, and they are not interchangeable: the capital-call pro-rata allocation and the final K-1 allocation each run a per-line round half-up pass followed by a largest-remainder reconciliation that forces the lines to sum exactly to the pool, whereas the distribution waterfall rounds each line individually and sums the rounded lines with no reconciliation pass, and the provisional K-1 allocation likewise rounds per line and deliberately allows the total to drift by a few cents from the offering's annual NOI. Percentages such as `preferred_return_pct_annual` and `carried_interest_pct` are decimal fractions (an eight percent preferred return is stored as 0.08, a twenty percent promote as 0.20).

### 2.7. Optimistic Concurrency Control

Two write operations guard against stale client state with optimistic concurrency control, and they are the only two endpoints that take a version field.

Creating a transfer request against a subscription requires the request body to carry `expected_subscription_version`, holding the value of the subscription's `version` the client last observed. If another writer has advanced that version in the meantime — most commonly because a prior transfer settled and legitimately reduced the subscription's `funded_cents` — the create is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412), preventing the client from initiating a transfer against a funded balance it has not observed.

Approving a distribution requires the request body to carry `expected_distribution_version`, holding the distribution's `version` as last observed by the approver. If the distribution's version has advanced since — for instance because the waterfall was recalculated and its distribution lines were regenerated — the approval is rejected with `ERR_STALE_DISTRIBUTION_VERSION` (HTTP 412). No other endpoint requires a version field. The syndication lifecycle actions (activate, suspend, close) and the offering lifecycle actions (open, close-to-new, reopen, final-close, dissolve) additionally accept an optional `expected_syndication_version` or `expected_offering_version` respectively; when supplied, the same stale-version comparison applies, and when omitted the action proceeds without a version check.

### 2.8. Logical Clock and Time-Dependent Rules

The server maintains a logical clock. On boot, before any clock adjustment, the current time is 2026-08-01T00:00:00Z. A sponsor-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the new `current_utc`; every time-dependent rule in the platform — preferred-return accrual windows, escrow due dates, accreditation expiry, future-period report validation, quarter boundaries — evaluates against this logical clock rather than wall time. Some state changes are lazy: a capital-call contribution whose due date has passed with insufficient funds becomes `DEFAULTED` the next time the contribution is read or written, or immediately observable once the clock is advanced past the due date. State-transition attempts made against a resource that is not in a state from which the requested transition is allowed are rejected with `ERR_INVALID_STATE` (HTTP 409).

### 2.9. Validation Ordering Across Guards

Where several guards protect a single endpoint, they are evaluated in a fixed order so that the most fundamental problem surfaces first. Authentication comes first — a request without well-formed `X-User-ID` and `X-User-Role` headers fails before anything else is examined — followed by the role-permission check. Path resolution comes next: every identifier in the URL must resolve before any business rule runs. Only then does the generic state-transition guard apply, and after it the domain-specific guards in their documented sequence for each workflow (for example, on a capital-call escrow receipt the overpayment check is evaluated before the past-due check, so an investor who wires too much money after the due date hears about the overpayment first). A required field that is missing, a value of the wrong type, or an unrecognized enum value is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Standing Up a Sponsor: Syndications, Investors, and Properties

A sponsor engagement begins when a `SponsorOperator` creates a `Syndication` with its display `syndication_name`, the `sponsor_legal_entity` of the general partner, and the two economic defaults that will flow down to every offering the syndication launches: `preferred_return_pct_annual`, the annual preferred-return rate offered across offerings, and `carried_interest_pct`, the GP promote share applied in the upper waterfall tiers. The new syndication starts in `DRAFT` status. Activation by a sponsor moves it to `ACTIVE`; an active syndication can later be suspended, which moves it to `SUSPENDED` and, as a cascade within the same request, pushes every `OPEN` offering under it into `CLOSED_TO_NEW_SUBSCRIPTIONS`. Re-activation from `SUSPENDED` returns the syndication to `ACTIVE` but does not reopen those offerings — the sponsor reopens each one deliberately. Closing a syndication is allowed only when every offering beneath it has reached `FINAL_CLOSE` or `DISSOLVED`; attempting to close over a still-open offering is rejected with `ERR_SYNDICATION_HAS_OPEN_OFFERINGS`. A successful close moves the syndication to its terminal `CLOSED` state and withdraws every non-terminal subscription anywhere beneath it. Each of these lifecycle actions increments the syndication's `version`.

Investors and properties are peer registries. Registering an investor captures `full_legal_name` exactly as it appears on tax records, `tax_id_last4` (the last four of the SSN or EIN, later used to bind K-1 packages), a unique portal-login `email`, and the investor's regulatory `investor_class`, one of `ACCREDITED`, `QUALIFIED_PURCHASER`, or `NON_ACCREDITED`. A freshly registered investor's `portal_access_status` starts at `INVITED`, and their `accreditation_expires_on` is null until the first successful accreditation verification stamps it ninety days out. Portal access is a parallel dimension with its own lifecycle — a sponsor can suspend portal access, moving `portal_access_status` to `SUSPENDED`, or revoke it outright to `REVOKED` — independent of anything happening to the investor's subscriptions. Registering a property captures its `property_legal_name`, `street_address`, and `acquisition_price_cents`; the property starts with `status` `OWNED` and later moves through `UNDER_CONTRACT_TO_SELL` to `SOLD` as capital events execute.

### 3.2. Opening an Offering

An offering ties a syndication to a property. Creating one under a syndication takes the `property_id` of the underlying asset, a human-readable `offering_name`, the `target_raise_cents` equity goal, the per-investor `min_subscription_cents` floor, and the `max_non_accredited_count` cap that keeps a Rule 506(b) offering within its allowance of non-accredited investors (typically 35). The server stamps the new offering with the `syndication_id` of its owning syndication, and every response body for a child resource carries the identifier of its parent — an offering's `syndication_id`, a subscription's or capital call's or quarterly report's or distribution's or K-1 package's `offering_id`, a document's or contribution's or transfer request's `subscription_id` (contributions additionally carry the `capital_call_id` of their call, and distribution lines the `distribution_id` of their distribution), and a transfer request's `from_subscription_id` naming the seller's subscription — so flat reads can be filtered by any of these keys without walking the nested path. The create also accepts optional offering-level overrides of `preferred_return_pct_annual` and `carried_interest_pct`. A new offering is `DRAFT`, with `total_committed_cents`, `total_funded_cents`, and `total_distributed_cents` all initialized to zero.

Opening an offering is gated on two things: the parent syndication must be `ACTIVE` — otherwise `ERR_SYNDICATION_NOT_ACTIVE` — and the linked property must still be `OWNED`, since an offering cannot fund a property already under contract to someone else (`ERR_PROPERTY_NOT_OWNED`). The moment an offering opens, its economics freeze into place: if the offering-level `preferred_return_pct_annual` was never set, the syndication's current value is copied onto the offering, and likewise for `carried_interest_pct`. Those copied values, not the syndication's live values, drive every later calculation for that offering.

From `OPEN`, a sponsor can stop new subscriptions by moving the offering to `CLOSED_TO_NEW_SUBSCRIPTIONS`, and can later reopen it — reopening returns the offering from `CLOSED_TO_NEW_SUBSCRIPTIONS` to `OPEN` and requires the syndication to be `ACTIVE` again, since a suspended syndication keeps all its offerings closed to new money. Moving from `CLOSED_TO_NEW_SUBSCRIPTIONS` to `FINAL_CLOSE` demands a clean book: no subscription beneath the offering may remain in `DRAFT`, `SUBMITTED`, `ACCREDITATION_VERIFIED`, `SUITABILITY_APPROVED`, or `AWAITING_FUNDING` (`ERR_OFFERING_HAS_OPEN_SUBSCRIPTIONS`), and every issued capital call must have reached `FULLY_FUNDED` or `CANCELLED` (`ERR_OFFERING_HAS_OPEN_CAPITAL_CALLS`). Dissolution is the last step and the strictest: the offering's `unreturned_capital_cents` — defined as `total_funded_cents` minus the cumulative return-of-capital already paid to limited partners — must be exactly zero (`ERR_OFFERING_UNRETURNED_CAPITAL`), and every distribution under the offering must be `PAID` or `CANCELLED` (`ERR_DISTRIBUTION_NOT_PAID`). Dissolution moves the offering to `DISSOLVED` and transitions all remaining `FUNDED` subscriptions to `WITHDRAWN`, with their accrued preferred return and unreturned capital flowing into the settlement of that final distribution.

### 3.3. From Draft Subscription to Funded Position

An investor begins a position by creating a subscription against an open offering, passing their own `investor_id` and the `committed_cents` they intend to fund; creating against an offering that is not `OPEN` is rejected with `ERR_OFFERING_NOT_OPEN`. The draft starts in `DRAFT` with `funded_cents`, `accrued_pref_cents`, and `unreturned_capital_cents` all at zero. Document collection happens against the draft: each upload names a `doc_type` — one of `SUBSCRIPTION_AGREEMENT`, `W9`, `ACCREDITATION_LETTER`, `ID_PROOF`, or `SUITABILITY_QUESTIONNAIRE` — plus a `file_uri` pointing at the stored blob, and the server stamps `received_at` and sets `review_status` to `PENDING_REVIEW`. A compliance officer then reviews each document; acceptance sets `review_status` to `ACCEPTED` and records the officer in `reviewed_by`, while rejection sets `REJECTED` with the same attribution. Document lists can be filtered by `doc_type` and `review_status` for the review queue.

Submitting the subscription is the first compliance gate, and its four checks run in a deliberate order. The offering must be `OPEN` (`ERR_OFFERING_NOT_OPEN`) — and since an offering can only be `OPEN` under an active syndication, a submit attempted while the syndication is suspended is rejected upstream with `ERR_SYNDICATION_NOT_ACTIVE`. Next, the three required document types — `SUBSCRIPTION_AGREEMENT`, `W9`, and `SUITABILITY_QUESTIONNAIRE` — must all be present and `ACCEPTED`; any gap yields `ERR_MISSING_REQUIRED_DOCUMENTS`. Only then is the commitment measured against the floor: `committed_cents` at least `min_subscription_cents`, else `ERR_BELOW_MIN_SUBSCRIPTION`. Finally, the 506(b) cap: if the investor's class is `NON_ACCREDITED`, the count of other subscriptions on this offering held by `NON_ACCREDITED` investors in any non-terminal state must already be below `max_non_accredited_count`, or the submit fails with `ERR_NON_ACCREDITED_CAP_REACHED`. A clean submission moves the subscription from `DRAFT` to `SUBMITTED`.

Accreditation verification is the compliance desk's first act, protected by segregation of duties. The verifying `ComplianceOfficer` may not be the investor who submitted the subscription — a self-verification attempt is rejected with `ERR_SELF_VERIFICATION_FORBIDDEN`. Three conditions must all hold, and the desk sees them surface in this order: the self-verification guard first, then the documentary requirement — an `ACCEPTED` document of type `ACCREDITATION_LETTER` must exist on the subscription, else `ERR_ACCREDITATION_DOC_MISSING` — and finally the investor-class rule, under which a commitment of 100000 dollars or more (that is, `committed_cents` of at least 10000000 cents) requires the investor to be `ACCREDITED` or `QUALIFIED_PURCHASER`, with anything less rejected as `ERR_INVESTOR_CLASS_INSUFFICIENT`. On success the subscription moves to `ACCREDITATION_VERIFIED`, `accreditation_verified_by` records the officer's `X-User-ID`, `accreditation_verified_at` stamps the current time, and the investor's `accreditation_expires_on` is stamped ninety days out.

Suitability approval is a second, deliberately different desk. The approving officer must not be the officer recorded in `accreditation_verified_by` — the same person verifying and approving is rejected with `ERR_SELF_APPROVAL_FORBIDDEN`. A successful approval does three things atomically: it records the approver in `suitability_verified_by`, it adds the subscription's `committed_cents` into the offering's `total_committed_cents`, and it chains the subscription straight through `SUITABILITY_APPROVED` into `AWAITING_FUNDING` within the same request — there is no direct API into `AWAITING_FUNDING`, because approval to fund is meaningless until money can move. Rejection is the other branch: the compliance desk can move the subscription from `ACCREDITATION_VERIFIED` to `SUITABILITY_REJECTED`, which clears `accreditation_verified_by` back to null, forcing a fresh accreditation verification if the investor tries again. An investor whose subscription was rejected can resubmit — provided the offering is still `OPEN` — returning the subscription to `SUBMITTED` for another pass through the gauntlet. An investor can also withdraw their own subscription from `DRAFT` or `SUBMITTED`, which moves it to `WITHDRAWN`; the withdraw is ownership-checked, so one investor cannot withdraw another's position.

### 3.4. Calling Capital and Moving Money Through Escrow

Once subscriptions are stacking up, the sponsor calls capital. Creating a capital call on an offering takes the `total_call_cents` to raise and the `due_date` by which funds must land; the call starts in `DRAFT` with `escrow_released_cents` at zero. Issuing the call requires the offering to be `OPEN` or `CLOSED_TO_NEW_SUBSCRIPTIONS` — an offering in any other state rejects the issuance with `ERR_OFFERING_NOT_ACCEPTING_CALLS`, and because issuance is also gated on the syndication being `ACTIVE`, a suspended syndication blocks it with `ERR_SYNDICATION_NOT_ACTIVE`. Issuance moves the call from `DRAFT` to `ISSUED` and does two things: it assigns the call's `call_index` as the next one-based sequence number across the offering's calls ordered by `created_at`, and it synthesizes one `CapitalCallContribution` for every subscription on the offering in `SUITABILITY_APPROVED`, `AWAITING_FUNDING`, or `FUNDED` status, in `created_at` order.

Each contribution's `amount_due_cents` is that subscription's pro-rata share of the call: the `total_call_cents` multiplied by the subscription's `committed_cents` and divided by the sum of `committed_cents` across all eligible subscriptions. The rounding discipline is pinned — every line is first rounded half-up to a whole cent individually, and then, if the rounded lines do not sum exactly to `total_call_cents`, the difference (which can never exceed one cent per eligible subscription in either direction) is allocated to the single line with the largest `amount_due_cents`, ties broken by the earliest subscription `created_at`. This largest-remainder adjustment guarantees the contributions sum exactly to the call amount.

Investors fund their own contributions through escrow. A receipt names the `amount_cents` being wired; the investor's `X-User-ID` must equal the `investor_id` of the subscription behind the contribution, otherwise `ERR_NOT_YOUR_CONTRIBUTION`. The receipt is state-guarded like any other transition: it is entertained only while the contribution is `PENDING`, `ESCROW_RECEIVED`, or `DEFAULTED`, and is rejected with `ERR_INVALID_STATE` against any other status (a `RELEASED` contribution). `DEFAULTED` is admitted so that a late wire is answered by the two business guards below rather than by the state guard: a contribution that defaulted for lateness is already past its call's `due_date`, so its wires reach the overpayment and past-due guards, while a contribution moved to `DEFAULTED` by a call cancellation may still have its `due_date` ahead, and a wire to it is handled by the same guards — an accepted wire is recorded with the contribution remaining `DEFAULTED`. Two business guards then apply in order: first the overpayment guard — the cumulative `amount_received_cents` after this receipt must not exceed `amount_due_cents`, or the wire is rejected with `ERR_ESCROW_OVERPAYMENT` — and then the timeliness guard, under which a receipt arriving after the call's `due_date` is rejected with `ERR_ESCROW_PAST_DUE`. A valid receipt adds `amount_cents` into `amount_received_cents`, stamps `received_at`, and moves the contribution from `PENDING` to `ESCROW_RECEIVED` once any money has landed. As soon as at least one contribution on an `ISSUED` call has reached `ESCROW_RECEIVED` while at least one sibling remains `PENDING` or received-but-not-yet-released, the call itself moves from `ISSUED` to `PARTIALLY_FUNDED`.

Escrow release is the sponsor's act, and it is gated on completeness: a contribution can be released only when the call is `ISSUED` or `PARTIALLY_FUNDED` and its `amount_received_cents` exactly equals `amount_due_cents` — a partial position cannot be released and is rejected with `ERR_ESCROW_INCOMPLETE`. Release moves the contribution to `RELEASED` and cascades in three directions: the call's `escrow_released_cents` grows by the released amount; the subscription's `funded_cents` grows by the same amount and, if the subscription was still `AWAITING_FUNDING`, it transitions to `FUNDED` with `funded_at` stamped at that moment; and the offering's `total_funded_cents` is recomputed as the sum of `funded_cents` across all `FUNDED` subscriptions. When the last outstanding contribution on a call releases, the call bubbles up to `FULLY_FUNDED`. A subscription's `ownership_pct` is its `funded_cents` divided by the offering's `total_funded_cents` at snapshot time, and its `unreturned_capital_cents` is its `funded_cents` minus whatever return-of-capital it has received across capital events.

Default is the grim branch. If a contribution's `due_date` passes with `amount_received_cents` still short of `amount_due_cents`, the contribution moves to `DEFAULTED` — observed lazily on the next read or write against it, or eagerly once the logical clock is advanced past the due date. Default does not touch the subscription's `funded_cents` or its status, but it does suspend the investor: the investor's `portal_access_status` flips to `SUSPENDED`, cutting off portal access until the sponsor sorts it out. A sponsor can also cancel an issued call outright, moving it from `ISSUED` to `CANCELLED`, but only while `escrow_released_cents` is still zero — once any money has been released to the operating account the call is beyond recall, and the cancel is rejected with `ERR_ESCROW_ALREADY_RELEASED`. Cancelling a call moves every contribution still `PENDING` or `ESCROW_RECEIVED` to `DEFAULTED` with the received amounts refunded; `escrow_released_cents` itself is unchanged by the cancellation.

### 3.5. Quarterly Reporting and the Distribution Waterfall

Sponsors report quarterly. Creating a quarterly report names the `report_year`, the `report_quarter` (one through four), the quarter's `noi_cents`, and physical `occupancy_pct` as a decimal fraction between zero and one. A new report is `DRAFT`. Neither at creation nor at publish time may the report's year and quarter lie in the future relative to the current logical time — a future period is rejected with `ERR_FUTURE_REPORT_PERIOD`. Publishing additionally requires the offering to be `OPEN`, `CLOSED_TO_NEW_SUBSCRIPTIONS`, or `FINAL_CLOSE` (`ERR_OFFERING_NOT_PUBLISHABLE`), and forbids a second `PUBLISHED` report for the same offering, year, and quarter (`ERR_DUPLICATE_QUARTERLY_REPORT`). Publication stamps `published_at` and computes the quarter's `distributable_cash_cents`: the `noi_cents` minus a reserve withholding of ten percent of NOI and a debt-service withholding of thirty percent of NOI, each withholding rounded half-up to a whole cent before subtraction, and the result floored at zero. This figure is a forward-looking estimate that feeds the quarterly-operating distribution variant; it is deliberately not the same number as a capital event's net proceeds.

A published report can be amended, moving it to `AMENDED`, but only while no distribution referencing it has reached `APPROVED` or `PAID` — a locked report rejects the amendment with `ERR_REPORT_LOCKED_BY_DISTRIBUTION`. Amendment leaves `published_at` untouched and recomputes `distributable_cash_cents`. Republishing an `AMENDED` report returns it to `PUBLISHED`, refreshing both `published_at` and the distributable-cash figure. Report lists can be filtered by `status`, `report_year`, and `report_quarter`.

Distributions come in two kinds, and the kind determines the lineage. A distribution's `distribution_kind` is `QUARTERLY_OPERATING` or `CAPITAL_EVENT`. A quarterly-operating distribution must name the `quarterly_report_id` of its source report and must leave `capital_event_id` null; a capital-event distribution does the reverse, naming `capital_event_id` and leaving `quarterly_report_id` null. Creation takes the `total_distributable_cents` pool and starts the distribution in `DRAFT`.

Calculation turns the pool into lines, and its guards run before any arithmetic: for a `QUARTERLY_OPERATING` distribution the linked report must be `PUBLISHED` (`ERR_REPORT_NOT_PUBLISHED`); for a `CAPITAL_EVENT` distribution the linked event must be `EXECUTED` (`ERR_CAPITAL_EVENT_NOT_EXECUTED`); the pool must be positive (`ERR_EMPTY_DISTRIBUTION_POOL`); and at least one subscription on the offering must be `FUNDED` (`ERR_NO_FUNDED_SUBSCRIPTIONS`). Calculation stamps `calculated_at` and synthesizes one `DistributionLine` per `FUNDED` subscription, ordered by `funded_at` ascending with `created_at` ascending as the tie-break, then runs the four-tier waterfall.

The waterfall allocates the pool tier by tier, and each per-LP amount is rounded half-up to a whole cent as it is computed, with the rounded lines then summed — the platform pins this per-line-then-sum order and never reconciles the waterfall's lines back to the pool. Tier 1 is return of capital: the tier-1 pool is the lesser of the total pool and the sum of every LP's `unreturned_capital_cents` snapshot at calculation time, and it is dealt to LPs in the fixed order, each LP receiving the lesser of their own unreturned capital and whatever remains of the tier-1 pool. Tier 2 is the preferred return: the tier-2 pool is the lesser of what the pool has left after tier 1 and the sum of every LP's accrued preferred return as of `calculated_at`, dealt the same way — each LP takes the lesser of their own accrual and the remaining tier-2 pool. Tier 3 is the GP catch-up: the GP receives one hundred percent of the next dollars until the GP's cumulative take equals the promote fraction of the sum of the total tier-2 preferred return plus the GP's own take. Solving that condition algebraically, the catch-up target is the offering's `carried_interest_pct` multiplied by the total tier-2 amount and divided by one minus the promote, rounded half-up; the tier-3 pool is the lesser of what remains in the pool after tiers 1 and 2 and that catch-up target, and it is attributed across LPs pro-rata to their tier-2 amounts — each LP's slice is the tier-3 pool multiplied by that LP's tier-2 amount and divided by the total tier-2 amount (with a division-by-zero guard treating an empty denominator as one), rounded half-up per line. Tier 4 is the residual profit split: whatever the pool still holds after tiers 1 through 3 is split so the LP side receives the promote-complement fraction — that is, the residual multiplied by one minus the `carried_interest_pct`, rounded half-up — and the GP side receives the rest. Each side is then dealt to LPs pro-rata by `funded_cents`: each LP's share of a side is that side's total multiplied by the LP's `funded_cents` and divided by the sum of `funded_cents` across all LPs (again guarding an empty denominator as one), rounded half-up per line.

The five line fields fall directly out of the tiers: `return_of_capital_cents` is the LP's tier-1 amount, `preferred_return_cents` is the tier-2 amount, `profit_split_lp_cents` is the LP-side tier-4 share, `profit_split_gp_cents` is the sum of that LP's tier-3 GP attribution and tier-4 GP share, and `total_cents` is the sum of all four components.

Approval of a `CALCULATED` distribution is the OCC-guarded step described in §2.7 — the request must carry `expected_distribution_version` matching the distribution's current `version`, or it fails with `ERR_STALE_DISTRIBUTION_VERSION` — and moves the distribution to `APPROVED`. Payment moves it to `PAID` and settles the books in one atomic cascade: every line's `paid_at` is stamped; each receiving subscription's `accrued_pref_cents` is reduced by the line's `preferred_return_cents` and its `unreturned_capital_cents` by the line's `return_of_capital_cents`; the offering's `total_distributed_cents` grows by `total_distributable_cents`; the offering's `unreturned_capital_cents` is recomputed; and if the distribution is of kind `CAPITAL_EVENT`, the linked capital event moves from `EXECUTED` to `DISTRIBUTED`. A distribution still in `DRAFT` or `CALCULATED` can instead be cancelled, moving it to `CANCELLED` and discarding all of its distribution lines.

### 3.6. Capital Events: Refinance and Sale

A capital event is announced against a property with an `event_kind` of `REFINANCE` or `SALE`, the `gross_proceeds_cents` the event makes available, and the `debt_payoff_cents` of that gross which must go to retiring existing debt. Announcement starts the event in `ANNOUNCED`, and a property may host at most one active event at a time — announcing a second while one is still `ANNOUNCED` or `EXECUTED` is rejected with `ERR_PROPERTY_HAS_ACTIVE_CAPITAL_EVENT`.

Execution is where the numbers lock. The property must be `OWNED` or `UNDER_CONTRACT_TO_SELL` — anything else rejects with `ERR_PROPERTY_NOT_TRANSACTABLE` — and the gross must strictly exceed the debt payoff, since an event whose `gross_proceeds_cents` does not exceed its `debt_payoff_cents` is rejected with `ERR_INSUFFICIENT_PROCEEDS`. A successful execution computes `net_distributable_cents` as `gross_proceeds_cents` minus `debt_payoff_cents`, an exact integer subtraction with no rounding, stamps `executed_at`, and — when the event is a `SALE` — moves the property's `status` to `SOLD`. That net figure is the actual cash available post-close, and it deliberately diverges from the quarterly forward estimate; the two numbers feed distributions of different kinds and are never mixed. From `EXECUTED`, the event advances to `DISTRIBUTED` automatically when a distribution linked to it reaches `PAID`. An event still merely `ANNOUNCED` can be cancelled, moving it to `CANCELLED`.

### 3.7. K-1 Preparation and the Dual-Variant Allocation

Tax coordination runs through K-1 packages. A sponsor creates one against an offering with the `tax_year` and the external `preparer_firm`; the package starts in `PREPARATION`. Submitting it for partner review requires the offering to have had at least one `FUNDED` subscription as of the last day of the tax year — without that base the submit is rejected with `ERR_NO_K1_BASE` — and moves the package to `PARTNER_REVIEW` while computing the `draft_k1_cents_by_subscription` map.

The provisional allocation works as follows. The offering's NOI for the year is the sum of `noi_cents` across all quarterly reports on the offering that are `PUBLISHED` or `AMENDED` and whose `report_year` equals the package's `tax_year`. Each `FUNDED` subscription — ordered by `funded_at` ascending, ties broken by `created_at` — receives a provisional share equal to that annual NOI multiplied by the subscription's `funded_cents` and divided by the total `funded_cents` across all funded subscriptions snapshotted at year-end, rounded half-up to a whole cent per line. The provisional map runs no reconciliation pass: the per-line rounding means the mapped values may drift a few cents from the annual NOI, and that drift is accepted because the numbers are for review only.

Finalization moves the package from `PARTNER_REVIEW` to `FINALIZED` and computes `final_k1_cents_by_subscription` from exactly the same inputs — same annual NOI, same funded positions at year-end — but with one difference: after each line is rounded half-up individually, a largest-remainder reconciliation forces the final map to sum exactly to the annual NOI. The signed difference between the annual NOI and the sum of the rounded lines is allocated to the single line belonging to the subscription with the largest `funded_cents`, ties broken by the earliest subscription `created_at`. The draft map is left untouched at finalization, frozen so the delta between provisional and final remains auditable; the two variants therefore differ from each other by at most the reconciliation amount on identical inputs.

Delivery moves the package from `FINALIZED` to `DELIVERED`. Each referenced investor then sees a K-1 record in their portal; delivery is passive and does not touch any session's `last_accessed_at`.

### 3.8. Preferred-Return Accrual: The Two Variants

Every `FUNDED` subscription accrues a preferred return continuously in the background. The accrual is computed lazily whenever a subscription's `accrued_pref_cents` is read, and eagerly for the whole input set when a distribution is calculated; committed-but-unfunded subscriptions accrue nothing. The accrual needs three inputs: the subscription's `funded_cents`, the offering's `preferred_return_pct_annual`, and the number of full calendar quarters elapsed between the subscription's `funded_at` and the as-of date — the current logical time on a read, or the distribution's `calculated_at` during a calculation. The count runs in whole calendar quarters and begins with the quarter immediately following the one containing `funded_at` — the quarter containing `funded_at` itself never counts, even when funding lands on its first instant. Each quarter thereafter counts as full once the as-of date has reached or passed that quarter's final calendar day: a subscription funded at any moment within Q1 sees one full quarter once the as-of date reaches Q2's last day, two once it reaches Q3's last day, and so on.

Which of two formulas applies is decided by the deal's promote. When the offering's `carried_interest_pct` is below 0.25, accrual is simple: the annual rate is taken for the fraction of a year the capital has been at work — `funded_cents` multiplied by the annual rate and by the count of full quarters divided by four, the whole product rounded half-up to a whole cent. When the `carried_interest_pct` is 0.25 or higher, the deal is treated as a high-promote structure and accrual compounds quarterly: one plus a quarter of the annual rate is raised to the power of the full-quarter count, one is subtracted, the result is multiplied by `funded_cents`, and the product is rounded half-up to a whole cent. For two or more elapsed quarters the compounding variant grows strictly faster than the simple one, which is the intended balance of LP economics against the richer promote.

### 3.9. Investor Transfers and Portal Access

An investor exits a position — wholly or partly — through a transfer request. Initiating one against a subscription names the prospective buyer's `to_investor_id` and the `transfer_cents` of funded balance to move; the offering must be `OPEN` for a new transfer request, otherwise the create is rejected with `ERR_OFFERING_NOT_OPEN`. The request also carries the OCC field `expected_subscription_version` described in §2.7: the subscription's `version` must not have advanced since the initiator last read it, or the create is rejected with `ERR_STALE_SUBSCRIPTION_VERSION`. Creating the request starts it in `PENDING_SPONSOR_REVIEW` and bumps the subscription's `version`, marking the position as under-transfer.

Sponsor review is the first gate. The sponsor can approve only if the source subscription is `FUNDED` (`ERR_SUBSCRIPTION_NOT_FUNDED`) and the requested `transfer_cents` is positive and does not exceed the source subscription's `funded_cents` (`ERR_TRANSFER_EXCEEDS_FUNDED`); approval moves the request to `PENDING_TRANSFER_AGENT`. The sponsor can instead reject, moving the request straight to `REJECTED`. The transfer agent then takes the second gate: the buyer must already be onboarded onto the same offering through a separate subscription that has reached `ACCREDITATION_VERIFIED` or beyond (`ERR_BUYER_NOT_ONBOARDED`), and the buyer may not be the seller — `to_investor_id` equal to the source subscription's `investor_id` is a self-transfer, rejected with `ERR_SELF_TRANSFER`. The agent's approval moves the request to `APPROVED`; the agent's rejection moves it to `REJECTED`.

Settlement is the agent's final act, moving the request from `APPROVED` to `SETTLED`, and it moves real balances. The source subscription's `funded_cents` falls by `transfer_cents`, and the buyer's `FUNDED` subscription on the same offering gains the same amount, leaving the offering's `total_funded_cents` unchanged. Accruals travel with the money on a strict pro-rata basis: the transfer ratio is `transfer_cents` divided by the source subscription's `funded_cents` as it stood before settlement, and the source's `accrued_pref_cents` and `unreturned_capital_cents` are each multiplied by that ratio, rounded half-up to whole cents, debited from the source, and credited to the buyer's subscription. If the transfer drains the source subscription to zero, it transitions from `FUNDED` to `WITHDRAWN`, and `settled_at` stamps the settlement time. The seller can cancel a request still sitting in `PENDING_SPONSOR_REVIEW` — ownership-checked against the source subscription's `investor_id` — moving it to `CANCELLED`.

Portal access is the investor's window into all of this. An investor whose `portal_access_status` is `ACTIVE` can mint a portal session; the server issues an opaque `session_token`, stamps `issued_at`, sets `expires_at` twelve hours later, and updates `last_accessed_at` on every portal read. If the investor's portal access is anything other than `ACTIVE` — still `INVITED`, or `SUSPENDED` (whether by sponsor action or by a defaulted capital call), or `REVOKED` — the session request is rejected with `ERR_PORTAL_ACCESS_DENIED`. Sponsors and compliance officers can list an investor's sessions for audit, and investors can read their own; session lists filter by `investor_id`.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with HTTP 201; all other successful operations — reads, state transitions, calculations — respond with HTTP 200. Every state-transition endpoint increments the affected resource's `version` by one unless otherwise noted. Request and response payloads are as narrated in §3; the table below is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /syndications | Create a Syndication (sponsor firm) | SponsorOperator |
| GET | /syndications | List syndications | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /syndications/{syndicationId} | Get a specific syndication | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| POST | /syndications/{syndicationId}/activate | Activate (or re-activate) a syndication | SponsorOperator |
| POST | /syndications/{syndicationId}/suspend | Suspend a syndication; cascades OPEN offerings to CLOSED_TO_NEW_SUBSCRIPTIONS | SponsorOperator |
| POST | /syndications/{syndicationId}/close | Close a syndication; all offerings must be FINAL_CLOSE or DISSOLVED | SponsorOperator |
| POST | /investors | Register an investor | SponsorOperator |
| GET | /investors | List investors | SponsorOperator, ComplianceOfficer, TransferAgent |
| GET | /investors/{investorId} | Get an investor (self or back-office) | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| POST | /investors/{investorId}/suspend-portal | Suspend investor portal access | SponsorOperator |
| POST | /investors/{investorId}/revoke-portal | Revoke investor portal access | SponsorOperator |
| POST | /investors/{investorId}/portal-sessions | Issue a portal session token | Investor |
| GET | /investors/{investorId}/portal-sessions | List an investor's portal sessions | Investor, SponsorOperator, ComplianceOfficer |
| POST | /properties | Register a property | SponsorOperator |
| GET | /properties | List properties | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /properties/{propertyId} | Get a specific property | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| POST | /syndications/{syndicationId}/offerings | Create an offering under a syndication | SponsorOperator |
| GET | /syndications/{syndicationId}/offerings | List offerings under a syndication | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /syndications/{syndicationId}/offerings/{offeringId} | Get a specific offering | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/open | Open an offering for subscriptions | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/close-to-new | Stop accepting new subscriptions | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/reopen | Re-open a closed-to-new offering | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/final-close | Move offering to FINAL_CLOSE (no open subscriptions/calls) | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/dissolve | Dissolve an offering (all capital returned, all distributions paid) | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions | Create a draft subscription | Investor |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions | List subscriptions on an offering | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId} | Get a specific subscription | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/submit | Investor submits subscription (validates documents, minimum, non-accredited cap) | Investor |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/verify-accreditation | ComplianceOfficer verifies accreditation | ComplianceOfficer |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/approve-suitability | ComplianceOfficer (different from verifier) approves suitability | ComplianceOfficer |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/reject-suitability | Reject suitability; accreditation_verified_by cleared | ComplianceOfficer |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/resubmit | Investor resubmits after rejection | Investor |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/withdraw | Investor withdraws | Investor |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/documents | Upload a subscription document | Investor |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/documents | List documents on a subscription | SponsorOperator, ComplianceOfficer, Investor |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/documents/{documentId} | Get a specific document | SponsorOperator, ComplianceOfficer, Investor |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/documents/{documentId}/accept | ComplianceOfficer accepts a document | ComplianceOfficer |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/documents/{documentId}/reject | ComplianceOfficer rejects a document | ComplianceOfficer |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/capital-calls | Create a capital call (DRAFT) | SponsorOperator |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/capital-calls | List capital calls on an offering | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/capital-calls/{capitalCallId} | Get a capital call | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/capital-calls/{capitalCallId}/issue | Issue a capital call; synthesize pro-rata contributions | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/capital-calls/{capitalCallId}/cancel | Cancel a DRAFT or ISSUED capital call | SponsorOperator |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/capital-calls/{capitalCallId}/contributions | List contributions on a call | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/capital-calls/{capitalCallId}/contributions/{contributionId} | Get a contribution | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/capital-calls/{capitalCallId}/contributions/{contributionId}/receive-escrow | Investor wires escrow funds (may be partial) | Investor |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/capital-calls/{capitalCallId}/contributions/{contributionId}/release-escrow | Release escrow to operating account | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/quarterly-reports | Create a quarterly report (DRAFT) | SponsorOperator |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/quarterly-reports | List quarterly reports | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/quarterly-reports/{quarterlyReportId} | Get a quarterly report | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/quarterly-reports/{quarterlyReportId}/publish | Publish a quarterly report; computes distributable_cash_cents | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/quarterly-reports/{quarterlyReportId}/amend | Amend a published report (locks if referenced by APPROVED/PAID distribution) | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/distributions | Create a distribution (DRAFT) | SponsorOperator |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/distributions | List distributions on an offering | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/distributions/{distributionId} | Get a distribution | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/distributions/{distributionId}/calculate | Run waterfall; synthesize DistributionLines | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/distributions/{distributionId}/approve | Approve a CALCULATED distribution (OCC-guarded) | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/distributions/{distributionId}/pay | Pay an APPROVED distribution | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/distributions/{distributionId}/cancel | Cancel a DRAFT or CALCULATED distribution | SponsorOperator |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/distributions/{distributionId}/lines | List distribution lines | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/distributions/{distributionId}/lines/{lineId} | Get a distribution line | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| POST | /syndications/{syndicationId}/properties/{propertyId}/capital-events | Announce a capital event (refinance or sale) | SponsorOperator |
| GET | /syndications/{syndicationId}/properties/{propertyId}/capital-events | List capital events on a property | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /syndications/{syndicationId}/properties/{propertyId}/capital-events/{capitalEventId} | Get a capital event | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| POST | /syndications/{syndicationId}/properties/{propertyId}/capital-events/{capitalEventId}/execute | Execute a capital event (locks net_distributable_cents) | SponsorOperator |
| POST | /syndications/{syndicationId}/properties/{propertyId}/capital-events/{capitalEventId}/cancel | Cancel an ANNOUNCED capital event | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/k1-packages | Create a K-1 package (PREPARATION) | SponsorOperator |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/k1-packages | List K-1 packages | SponsorOperator, ComplianceOfficer, TransferAgent |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/k1-packages/{k1PackageId} | Get a K-1 package | SponsorOperator, ComplianceOfficer, TransferAgent |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/k1-packages/{k1PackageId}/submit-for-review | Submit for partner review; computes draft K-1 map | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/k1-packages/{k1PackageId}/finalize | Finalize; computes final K-1 map reconciled against NOI | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/k1-packages/{k1PackageId}/deliver | Deliver to investors (portal-visible) | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/transfer-requests | Investor initiates a transfer (OCC-guarded) | Investor |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/transfer-requests | List transfer requests on a subscription | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/transfer-requests/{transferRequestId} | Get a transfer request | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/transfer-requests/{transferRequestId}/sponsor-approve | Sponsor approves transfer | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/transfer-requests/{transferRequestId}/sponsor-reject | Sponsor rejects transfer | SponsorOperator |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/transfer-requests/{transferRequestId}/agent-approve | Transfer agent approves | TransferAgent |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/transfer-requests/{transferRequestId}/agent-reject | Transfer agent rejects | TransferAgent |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/transfer-requests/{transferRequestId}/settle | Settle an APPROVED transfer | TransferAgent |
| POST | /syndications/{syndicationId}/offerings/{offeringId}/subscriptions/{subscriptionId}/transfer-requests/{transferRequestId}/cancel | Investor cancels a PENDING_SPONSOR_REVIEW transfer | Investor |
| GET | /offerings | Flat filtered list of Offerings (reverse-reachability for FKs) | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /offerings/{offeringId} | Flat single-resource GET for an Offering | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /subscriptions | Flat filtered list of Subscriptions | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /subscriptions/{subscriptionId} | Flat single-resource GET for a Subscription | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /documents | Flat filtered list of SubscriptionDocuments | SponsorOperator, ComplianceOfficer, Investor |
| GET | /documents/{documentId} | Flat single-resource GET for a SubscriptionDocument | SponsorOperator, ComplianceOfficer, Investor |
| GET | /capital-calls | Flat filtered list of CapitalCalls | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /capital-calls/{capitalCallId} | Flat single-resource GET for a CapitalCall | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /contributions | Flat filtered list of CapitalCallContributions | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /contributions/{contributionId} | Flat single-resource GET for a CapitalCallContribution | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /quarterly-reports | Flat filtered list of QuarterlyReports | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /quarterly-reports/{quarterlyReportId} | Flat single-resource GET for a QuarterlyReport | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /distributions | Flat filtered list of Distributions | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /distributions/{distributionId} | Flat single-resource GET for a Distribution | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /distribution-lines | Flat filtered list of DistributionLines | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /distribution-lines/{lineId} | Flat single-resource GET for a DistributionLine | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /capital-events | Flat filtered list of CapitalEvents | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /capital-events/{capitalEventId} | Flat single-resource GET for a CapitalEvent | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /k1-packages | Flat filtered list of K1Packages | SponsorOperator, ComplianceOfficer, TransferAgent |
| GET | /k1-packages/{k1PackageId} | Flat single-resource GET for a K1Package | SponsorOperator, ComplianceOfficer, TransferAgent |
| GET | /transfer-requests | Flat filtered list of TransferRequests | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /transfer-requests/{transferRequestId} | Flat single-resource GET for a TransferRequest | SponsorOperator, ComplianceOfficer, TransferAgent, Investor |
| GET | /portal-sessions | Flat filtered list of InvestorPortalSessions | SponsorOperator, ComplianceOfficer |
| GET | /portal-sessions/{sessionId} | Flat single-resource GET for an InvestorPortalSession | SponsorOperator, ComplianceOfficer, Investor |
| POST | /_clock/set_current_utc | Advance the server's logical clock to a supplied `to_iso8601` instant; returns `current_utc` | SponsorOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_SYNDICATION_NOT_FOUND | 404 |
| ERR_OFFERING_NOT_FOUND | 404 |
| ERR_SUBSCRIPTION_NOT_FOUND | 404 |
| ERR_INVESTOR_NOT_FOUND | 404 |
| ERR_PROPERTY_NOT_FOUND | 404 |
| ERR_DOCUMENT_NOT_FOUND | 404 |
| ERR_CAPITAL_CALL_NOT_FOUND | 404 |
| ERR_CONTRIBUTION_NOT_FOUND | 404 |
| ERR_QUARTERLY_REPORT_NOT_FOUND | 404 |
| ERR_DISTRIBUTION_NOT_FOUND | 404 |
| ERR_CAPITAL_EVENT_NOT_FOUND | 404 |
| ERR_K1_PACKAGE_NOT_FOUND | 404 |
| ERR_TRANSFER_REQUEST_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_SYNDICATION_NOT_ACTIVE | 409 |
| ERR_OFFERING_NOT_OPEN | 409 |
| ERR_OFFERING_NOT_ACCEPTING_CALLS | 409 |
| ERR_PROPERTY_NOT_TRANSACTABLE | 409 |
| ERR_PROPERTY_NOT_OWNED | 409 |
| ERR_SUBSCRIPTION_NOT_FUNDED | 409 |
| ERR_SELF_VERIFICATION_FORBIDDEN | 403 |
| ERR_SELF_APPROVAL_FORBIDDEN | 403 |
| ERR_INVESTOR_CLASS_INSUFFICIENT | 422 |
| ERR_ACCREDITATION_DOC_MISSING | 422 |
| ERR_MISSING_REQUIRED_DOCUMENTS | 422 |
| ERR_BELOW_MIN_SUBSCRIPTION | 422 |
| ERR_NON_ACCREDITED_CAP_REACHED | 422 |
| ERR_DUPLICATE_QUARTERLY_REPORT | 409 |
| ERR_TRANSFER_EXCEEDS_FUNDED | 422 |
| ERR_BUYER_NOT_ONBOARDED | 422 |
| ERR_SELF_TRANSFER | 422 |
| ERR_REPORT_LOCKED_BY_DISTRIBUTION | 409 |
| ERR_PROPERTY_HAS_ACTIVE_CAPITAL_EVENT | 409 |
| ERR_REPORT_NOT_PUBLISHED | 422 |
| ERR_CAPITAL_EVENT_NOT_EXECUTED | 422 |
| ERR_ESCROW_OVERPAYMENT | 422 |
| ERR_ESCROW_PAST_DUE | 422 |
| ERR_ESCROW_INCOMPLETE | 422 |
| ERR_ESCROW_ALREADY_RELEASED | 409 |
| ERR_INSUFFICIENT_PROCEEDS | 422 |
| ERR_NO_FUNDED_SUBSCRIPTIONS | 422 |
| ERR_EMPTY_DISTRIBUTION_POOL | 422 |
| ERR_OFFERING_HAS_OPEN_SUBSCRIPTIONS | 409 |
| ERR_OFFERING_HAS_OPEN_CAPITAL_CALLS | 409 |
| ERR_OFFERING_UNRETURNED_CAPITAL | 409 |
| ERR_DISTRIBUTION_NOT_PAID | 409 |
| ERR_NO_K1_BASE | 422 |
| ERR_FUTURE_REPORT_PERIOD | 422 |
| ERR_STALE_SUBSCRIPTION_VERSION | 412 |
| ERR_STALE_DISTRIBUTION_VERSION | 412 |
| ERR_PORTAL_ACCESS_DENIED | 403 |
| ERR_NOT_YOUR_CONTRIBUTION | 403 |
| ERR_INVALID_REQUEST | 400 |
