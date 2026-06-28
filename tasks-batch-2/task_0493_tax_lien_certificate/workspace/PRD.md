# Tax Lien Certificate API — Product Requirements Document

## 1. Introduction

When a property owner falls behind on property taxes, the county does not simply wait. It packages the delinquent obligation into a tradable instrument — a tax lien certificate — and sells it to private investors at a public auction. The investor advances the county the unpaid tax, and in exchange acquires the right to collect that amount back from the property owner, plus statutory interest, when the owner eventually redeems. If the owner never redeems within the statutory window, the certificate holder may pursue a tax deed and ultimately take title to the property. This API models that entire machine end to end: the configuration of a county's statutory parameters, the registration of delinquent parcels, the auction itself (in either a bid-down-the-rate or a cash-premium variant), the issuance of certificates to winning bidders, the day-by-day accrual of interest, the payment of subsequent years' taxes by the holder, the redemption payoff, the foreclosure and deed-award process, and the distribution of any surplus back to the former owner.

The system serves three constituencies whose duties must remain strictly separated. The **CountyTreasurer** runs the public process — opening and closing sales, issuing certificates through the close cascade, processing redemptions, and adjudicating deed applications. **Investors** participate in the market — bidding, holding certificates, paying subsequent taxes, transferring certificates by assignment, and applying for deeds. **Auditors** observe everything but touch nothing. Because real money flows through escrow accounts and because the order of operations determines who is made whole and who receives an overage, the API treats interest accrual, escrow accounting, and state transitions as first-class, auditable, immediately-consistent operations. A logical clock — never the wall clock — governs every accrual and deadline so that the financial mathematics are fully reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint. The API is mounted under the `/counties` prefix.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly three roles, spelled precisely as `CountyTreasurer`, `Investor`, and `Auditor`. A request that omits either header, or whose `X-User-Role` is not one of these three declared roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is valid but is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Investor`, `X-User-ID` is the `id` of the acting `Investor` entity; ownership checks on any resource that references an `Investor` compare that resource's investor foreign-key field to `X-User-ID`. In practice this is what binds a bid's `investor_id`, a sub-tax's payer, an assignment's `from_investor_id`, and a deed application's `applicant_investor_id` to the authenticated caller. When `X-User-Role` is `CountyTreasurer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may read it (notably to enforce segregation of duties at sale close, comparing it against the identifiers of winning bidders) but it does not correspond to any entity's `id`. When `X-User-Role` is `Auditor`, `X-User-ID` is likewise an opaque identifier not tied to any persisted entity; the auditor may read every resource but may mutate none.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. The single exception is the assignment list for a certificate, which is returned in ascending `seq` order so that the transfer chain reads in the order it occurred.

Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Time-Driven Behavior

Every accrual, scheduling check, and deadline in this system reads a single server-managed **logical clock**, never the host's wall-clock time. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to real time. A treasurer-operated test-driving capability advances or rewinds the clock to a supplied `to_iso8601` instant, and the response reports the resulting `current_utc`. Because interest is a function of elapsed days, all reproducibility of the financial mathematics depends on this clock being the sole source of "now."

### 2.5. Common Resource Properties

Every resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits recording when it was first created. Resources that can be modified after creation additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at its initial value on creation and increments by one on every mutation. All entities in this system — counties, parcels, investors, sales, listings, bids, certificates, subsequent taxes, redemptions, assignments, deed applications, and surplus distributions — carry the full set of `id`, `created_at`, `updated_at`, and `version`. The `version` field is the basis for the optimistic-concurrency checks described in §2.7.

### 2.6. Monetary Precision, Day-Count, and Interest Accrual

All monetary amounts in this system are integer counts of cents, and all interest rates are integer counts of **basis points** (bps), where 10,000 basis points equals 100 percent. There are no fractional cents and no fractional basis points stored anywhere.

Interest is **simple interest** accrued over whole elapsed days. The number of accrual days between two logical-clock instants is the floor of the difference between them measured in seconds, divided by 86,400 seconds per day; any partial day is discarded entirely, so day zero accrues nothing and accrual begins only once a full day has elapsed. Concretely, redeeming exactly a whole number of days after issuance — at the issuance instant plus that many multiples of 86,400 seconds — yields that many accrual days, and redeeming one second earlier yields one fewer day.

A single interest component is computed as the principal multiplied by the applicable annual rate in basis points, multiplied by the elapsed accrual days, divided by the product of 10,000 and the county's `day_count_basis` (its days-in-year divisor, which is either 360 or 365, defaulting to 365). Each such component is rounded to whole cents using the **round-half-up** convention. The system never sums raw products and rounds once at the end: it rounds each component — the face-interest component, each individual subsequent-tax interest amount, and the premium interest — to whole cents first, and only then adds the rounded components together. This per-component-then-sum ordering is mandatory wherever interest appears, both in a live redemption and in the snapshot taken at deed-application time.

### 2.7. Optimistic Concurrency Control

Three write operations require the client to prove it is acting on a current view of a parent resource by supplying that parent's last-observed `version`. These are the only operations that take a version field; no other endpoint accepts one.

When placing a bid on a listing, the request body must carry `expected_listing_version` equal to the target `SaleListing`'s current `version`. If a withdrawal (or any other mutation) has advanced the listing's `version` since the client last read it, the placement is rejected with `ERR_STALE_VERSION` at HTTP status 412, forcing the investor to re-read the listing's current status before committing escrow. When adding a subsequent tax to a certificate, the request body must carry `expected_certificate_version` equal to the certificate's current `version`; if a redemption, assignment, or deed application has advanced that `version` since the client last read it, the add is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the payer to re-read the certificate — whose holder or status may have changed — before committing the outlay. When recording an assignment on a certificate, the request body must likewise carry `expected_certificate_version` equal to the certificate's current `version`; if a prior assignment (or other mutation) has already advanced the `version`, the record is rejected with `ERR_STALE_VERSION` (HTTP 412), keeping the transfer chain single-threaded and ordered so that a second assignment cannot be recorded against a view in which `from_investor_id` was still the holder.

### 2.8. Hierarchical Consistency and Cascading State

State in this system is layered, and many transitions ripple across aggregate boundaries. A parcel's `status` is never set directly by a client; it is a derived posture driven by the certificate currently attached to the parcel. When a listing is attached, the parcel moves from `DELINQUENT` to `ON_SALE`; when a certificate is issued, the parcel becomes `LIENED` and its `active_certificate_id` points at that certificate; when the certificate is redeemed the parcel returns to `REDEEMED` with `active_certificate_id` cleared to null; and when a deed is awarded the parcel becomes `DEEDED`, again with `active_certificate_id` cleared. Each such ripple is itself a mutation of the affected resource: the resource's `updated_at` is refreshed and its `version` is incremented. Where a single operation mutates several resources — the close cascade being the most far-reaching — each affected resource independently records its own `updated_at` and `version` bump.

### 2.9. Nested Resource Retrieval and Referential Scope

Many paths nest several identifiers — a bid lives under a listing, which lives under a sale, which lives under a county. The server validates path identifiers strictly left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier in the path that does not resolve to an existing resource, before considering anything further to its right. Separately, when a request body carries foreign keys, those references must resolve within the correct county scope: a listing's `parcel_id` must name a parcel whose `county_id` equals the county in the path, a referenced investor must exist, and a certificate must belong to the path county. A body foreign key that points outside the correct county scope is rejected with `ERR_CROSS_COUNTY_REFERENCE`. Every entity also exposes a flat single-resource read and a flat filtered-list read whose filters cover each foreign-key field, so any relationship can be traversed in reverse by querying the child collection on the parent's identifier.

### 2.10. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order, and the first failure determines the response. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization per the access-control matrix (`ERR_FORBIDDEN_ROLE`), then left-to-right existence of every path resource (`ERR_NOT_FOUND`), then cross-county referential integrity of body foreign keys (`ERR_CROSS_COUNTY_REFERENCE`), then basic request-body shape — required fields present, enums in range, integers non-negative where required, and the OCC field present where one is required (`ERR_INVALID_REQUEST`). Only after the body is well-formed does the system check optimistic concurrency, comparing the supplied `expected_listing_version` or `expected_certificate_version` against the parent's current `version` (`ERR_STALE_VERSION`). Next it confirms the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). It then applies segregation-of-duties (`ERR_SEGREGATION_OF_DUTIES`), temporal gates on scheduling and deadlines (`ERR_SALE_NOT_DUE` and `ERR_REDEMPTION_PERIOD_OPEN`), the holder-identity requirement (`ERR_NOT_CERTIFICATE_HOLDER`), bid-shape rules (`ERR_INVALID_BID`), uniqueness rules (`ERR_DUPLICATE_SUB_TAX`), escrow sufficiency (`ERR_INSUFFICIENT_ESCROW`), and finally the deed-sale floor (`ERR_BID_BELOW_MINIMUM`). A semantic field-constraint violation that is not one of the more specific cases above surfaces as `ERR_VALIDATION`. This ordering matters: a stale-version failure, for instance, is reported before a state-machine failure, and a missing required field is reported before any concurrency or state consideration.

### 2.11. Segregation of Duties

The county process is built on a separation between those who run the auction and those who profit from it. Bidding is reserved to the `Investor` role; a `CountyTreasurer` may never place a bid. At sale close, the treasurer who runs the award cascade must not be acting as the `X-User-ID` of any investor that holds a winning bid in that sale. Either of these violations is rejected with `ERR_SEGREGATION_OF_DUTIES`.

## 3. Business Logic & Workflows

### 3.1. Configuring a County and Registering Parcels

Everything begins with a county configuration, created by a `CountyTreasurer`. A county is described by its `name` and two-letter `state_code`, and it fixes the statutory parameters that govern every sale and certificate beneath it. The `max_interest_rate_bps` is the statutory ceiling rate (for example, 1,600 basis points for sixteen percent) and serves as the starting rate of a bid-down auction; it must be at least 1 and at most 5,000 basis points. The `bid_down_increment_bps` is the minimum step by which bidders may undercut the rate; it must be at least 1, and the ceiling rate must be an exact integer multiple of it. The `redemption_period_days` (at least 1) is the number of days after a certificate is issued during which the owner may still redeem before any deed application is permitted. The `penalty_rate_bps` is a flat mandatory penalty applied to the base tax at redemption regardless of how much time has elapsed; it is at least 0 and defaults to 0 when omitted. The `sub_tax_interest_rate_bps` is the fixed annual rate applied to subsequent-tax principal, often the statutory ceiling and independent of any winning bid rate; it must be between 1 and 5,000 basis points inclusive.

Two boolean flags set the auction style. The `premium_bidding_enabled` flag, defaulting to false, decides whether the county runs cash-premium auctions or rate-bid-down auctions. The `premium_earns_interest` flag, defaulting to false, decides whether an overbid premium is returned to the holder with interest at redemption or simply forfeited. The `day_count_basis` chooses the days-in-year divisor for interest accrual and must be either 360 or 365, defaulting to 365.

A `CountyTreasurer` registers each delinquent property as a **parcel** under its county. A parcel records the county it belongs to, its `apn` (the assessor's parcel number, unique within a county), the `owner_name`, the `assessed_value_cents` (at least 0, used later in surplus-eligibility reasoning), and the `base_tax_due_cents` — the original delinquent tax principal that will become the face amount of the lien, which must be at least 1. A freshly registered parcel has `status` of `DELINQUENT` and a null `active_certificate_id`. Parcels can be listed within a county and filtered by `status`.

### 3.2. Investors, Deposits, and the Escrow Ledger

An **investor** is registered with a `legal_name` and a `tax_id` (unique across all investors); either an `Investor` registering themselves or a `CountyTreasurer` onboarding them may create the record. A new investor starts with an `escrow_balance_cents` of 0, a `deposit_total_cents` of 0, and `registered` set to false. Funding the escrow account is done by posting a deposit of `amount_cents`; the first deposit flips `registered` to true. Each deposit raises both `deposit_total_cents` and `escrow_balance_cents` by `amount_cents`.

The `escrow_balance_cents` is the investor's available, uncommitted money, and the system maintains it as a running ledger. Beginning from the sum of all deposits, it subtracts the permanently committed cost of every winning bid (face amount plus any premium), adds back every hold that was released when a bid lost or was refunded, subtracts the principal of every posted subsequent tax this investor paid, subtracts the deed-filing cost of every deed application this investor filed, adds every redemption credit received while holding a certificate (the total payoff less any filed-deed-cost passthrough), and adds the lien-satisfied amount credited when a deed this investor held is awarded. A placed bid does not yet commit money; it places a **hold** that reserves the bid's exposure (face amount plus premium for a premium auction, or just the face amount for a rate-bid-down auction) against the available balance. The `deposit_total_cents` is simply the cumulative sum of deposits and never decreases. Any operation whose hold or outlay would drive `escrow_balance_cents` below zero is rejected with `ERR_INSUFFICIENT_ESCROW`.

### 3.3. Building and Opening a Sale

A `CountyTreasurer` creates a **tax sale** under a county with a `sale_name` and a `scheduled_at` instant — the earliest logical-clock moment at which the sale may open. The `sale_type` is not chosen by the caller; it is fixed at creation from the county's `premium_bidding_enabled` flag, becoming `PREMIUM` when premium bidding is enabled and `RATE_BID_DOWN` otherwise. A new sale is in `DRAFT` status with a `listing_count` of 0.

Into a `DRAFT` (or still-open) sale, the treasurer attaches delinquent parcels as **listings**. Creating a listing names a `parcel_id`; the listing copies its `opening_rate_bps` from the county's `max_interest_rate_bps` at that moment, starts in `LISTED` status with a null `winning_bid_id` and a null `certificate_id`, moves the referenced parcel from `DELINQUENT` to `ON_SALE`, and increments the sale's `listing_count`. Each listing records the `sale_id` of the sale it belongs to. Listings can be browsed for a sale — filtered by that `sale_id` — and further filtered by `parcel_id` or `status`.

Opening a sale advances it from `DRAFT` to `OPEN` and is the gate before bidding. The sale must currently be in `DRAFT`; if it is not, the request is rejected with `ERR_INVALID_STATE`. The open is permitted only once the logical clock has reached or passed the sale's `scheduled_at` — opening earlier yields `ERR_SALE_NOT_DUE`. A sale with no listings cannot open; an attempt with a `listing_count` of zero is rejected with `ERR_SALE_EMPTY`.

A treasurer may also **withdraw** a listing before the sale closes, transitioning it from `LISTED` to `WITHDRAWN`. Withdrawal is allowed only while the listing is `LISTED` and its parent sale is in `DRAFT` or `OPEN`; otherwise it is rejected with `ERR_INVALID_STATE`. On withdrawal, every `PLACED` bid on that listing moves to `REFUNDED` and its escrow hold is released back to the bidder, and the parcel reverts from `ON_SALE` to `DELINQUENT` provided no other still-`LISTED` listing references it. The withdrawal increments the listing's `version`, which is precisely why a bid carrying a now-stale `expected_listing_version` will be turned away.

### 3.4. Bidding

While a sale is `OPEN`, an `Investor` places a **bid** on a listing. A bid names the bidding `investor_id`, carries the OCC field `expected_listing_version`, and — depending on the auction type — either a `rate_bps` or a `premium_cents`. In a rate-bid-down auction the bidder competes by accepting a lower interest rate: the submitted `rate_bps` must be at most the listing's `opening_rate_bps` and must be a positive multiple of the county's `bid_down_increment_bps`; a `rate_bps` that exceeds the opening rate or is not such a multiple is rejected with `ERR_INVALID_BID`, and `premium_cents` is ignored, treated as 0. In a premium auction the bidder competes by offering more cash above face: the submitted `premium_cents` must be at least 0, the `rate_bps` is omitted and ignored, and a negative premium is rejected with `ERR_INVALID_BID`. A successfully placed bid enters `PLACED` status, places the appropriate escrow hold (face amount plus premium for a premium sale, or face amount alone for a rate-bid-down sale), and increments the listing's `version` by one. If the hold would push the bidder's `escrow_balance_cents` below zero, the bid is rejected with `ERR_INSUFFICIENT_ESCROW`. Bids on a listing can be listed and filtered by `investor_id` or `status`.

### 3.5. Closing the Sale: the Award Cascade

Closing a sale is the pivotal event, transitioning the sale from `OPEN` to `CLOSED` and running the award cascade that turns auctions into certificates. The sale must be `OPEN`, or the close is rejected with `ERR_INVALID_STATE`. The treasurer running the close must not be acting as the `X-User-ID` of any investor holding a winning bid, on pain of `ERR_SEGREGATION_OF_DUTIES`.

For each listing still `LISTED` that has at least one `PLACED` bid, the system selects a winner. The candidate set is exactly the listing's `PLACED` bids; bids already `LOST` or `REFUNDED` are excluded. In a rate-bid-down sale the winner is the bid with the lowest `rate_bps`, and ties at an equal rate are broken in favor of the earliest-created bid; the certificate then accrues at that winner's own `rate_bps` and carries a premium of 0. In a premium sale the winner is the bid offering the highest `premium_cents`, again breaking ties in favor of the earliest-created bid; the certificate accrues at the county's `max_interest_rate_bps` and carries the winner's `premium_cents`. The winning bid moves to `WON` and every other bid on that listing moves to `LOST`. The winner's hold converts to a permanent commitment (face amount plus premium debited for good, with no further escrow change), while each losing bidder's hold is released and credited back to their `escrow_balance_cents`.

Winning a listing makes it `SOLD`: its `winning_bid_id` and `certificate_id` are filled in, and a **certificate** is issued — this is a transitive cascade from listing to bid to certificate to parcel. A listing that is still `LISTED` but has zero `PLACED` bids is **struck off** to `STRUCK_OFF` and produces no certificate; its parcel reverts from `ON_SALE` to `DELINQUENT` unless some other path has already liened it. After the close, settling the sale advances it from `CLOSED` to `SETTLED`; settlement requires the sale to be `CLOSED` (otherwise `ERR_INVALID_STATE`), finalizes the event, and leaves the certificates already issued at close untouched.

### 3.6. The Certificate and Its Issuance

A **certificate** records the `county_id`, `parcel_id`, and `listing_id` it sprang from, and its `holder_investor_id` — the current holder, which begins as the winning bidder and changes only by assignment. At issuance its `face_amount_cents` is set to the parcel's `base_tax_due_cents` (at least 1), its `rate_bps` is the awarded rate (the winning bid's rate for a rate-bid-down sale, or the county ceiling for a premium sale), and its `premium_cents` is the overbid paid (0 for rate-bid-down). The `issued_at` timestamp is the logical-clock instant of issuance and the point from which face interest accrues, while `redeem_deadline_at` is `issued_at` advanced by the county's `redemption_period_days` and marks the earliest instant a deed application is allowed. A certificate tracks `sub_tax_total_cents` — the running sum of principal across its posted subsequent taxes — and `assignment_seq`, the count of completed transfers, which is 0 at issuance. A freshly issued certificate is `ACTIVE`. Certificates can be read directly and listed in a county, filtered by `parcel_id`, `listing_id`, `holder_investor_id`, `county_id`, or `status`.

### 3.7. Paying Subsequent Taxes

Once a holder owns a certificate, each new year's delinquent tax can be folded into the same lien rather than auctioned separately. The current holder — and only the current holder — pays a **subsequent tax** against the certificate, identifying the paying `investor_id`, the `tax_year` it covers, and the `principal_cents` advanced (at least 1), and supplying `expected_certificate_version` for the concurrency check. The payer must equal the certificate's current `holder_investor_id`; a non-holder attempt is rejected with `ERR_NOT_CERTIFICATE_HOLDER`. Each `tax_year` may be paid only once per certificate; a duplicate year is rejected with `ERR_DUPLICATE_SUB_TAX`. The payment must be coverable by the payer's escrow, or it is rejected with `ERR_INSUFFICIENT_ESCROW`. A successful payment is `POSTED`, stamps `posted_at` with the current logical-clock instant (the point from which that sub-tax's interest accrues at the county's `sub_tax_interest_rate_bps`), debits the holder's escrow by the principal, recomputes the certificate's `sub_tax_total_cents`, and increments the certificate's `version` by one. Subsequent taxes can be listed per certificate and filtered by `investor_id` or `status`. A subsequent tax sits in `POSTED` status until the lien is resolved, at which point it becomes `REDEEMED`.

### 3.8. Assigning a Certificate to Another Investor

A certificate is a transferable asset. An `Investor` records an **assignment** moving it from the current holder to another investor, supplying `from_investor_id` (which must be the current holder), `to_investor_id` (the assignee), a `consideration_cents` figure for the cash the assignee paid the assignor (at least 0), and `expected_certificate_version` for the concurrency check. The assignor must be the current `holder_investor_id`, or the record is rejected with `ERR_NOT_CERTIFICATE_HOLDER`, and the assignee must differ from the assignor — an assignment whose `to_investor_id` equals its `from_investor_id` is rejected with `ERR_DUPLICATE_SUB_TAX`. A recorded assignment receives the next `seq` (a 1-based position in the certificate's transfer chain), enters the terminal `RECORDED` status, repoints the certificate's `holder_investor_id` to the assignee, increments the certificate's `assignment_seq`, and increments the certificate's `version` by one. Because the version advances, any second assignment that still carries the pre-transfer version is rejected as stale, which is what keeps the chain single-threaded. Assignments are listed per certificate in ascending `seq` order and may be filtered by `from_investor_id`.

### 3.9. Redemption and the Payoff Calculation

Redemption is the owner buying back the lien, and it is processed by a `CountyTreasurer`. A certificate may be redeemed while it is `ACTIVE`, and also while it is `FORECLOSURE_PENDING` so long as the pending deed application has not yet been awarded; a redemption attempt against a certificate in any other state is rejected with `ERR_INVALID_STATE`, and if the certificate is `FORECLOSURE_PENDING` but its deed application has already advanced to awarded, the attempt is rejected with `ERR_DEED_ALREADY_AWARDED`. A non-mutating payoff quote is also available at the current logical-clock instant, returning `face_payoff_cents`, `face_interest_cents`, `penalty_cents`, `sub_tax_payoff_cents`, `sub_tax_interest_cents`, `premium_refund_cents`, `total_payoff_cents`, and the `as_of` instant it was computed at.

Processing a redemption creates a **redemption** record stamped with `redeemed_at` (the logical-clock payoff instant) and computes the payoff as follows. The `face_payoff_cents` is the certificate's `face_amount_cents` repaid in full. The `face_interest_cents` is simple interest on the face: the face amount multiplied by the certificate's `rate_bps`, multiplied by the whole elapsed days from `issued_at` to `redeemed_at`, divided by 10,000 times the county's `day_count_basis`, rounded half-up to whole cents. The `penalty_cents` is the flat penalty: the face amount multiplied by the county's `penalty_rate_bps`, divided by 10,000, rounded half-up. The `sub_tax_payoff_cents` is the sum of `principal_cents` across all `POSTED` subsequent taxes (those already `REDEEMED` are excluded). The `sub_tax_interest_cents` is computed by taking each `POSTED` sub-tax individually — its `principal_cents` multiplied by the county's `sub_tax_interest_rate_bps`, multiplied by the whole elapsed days from that sub-tax's own `posted_at` to `redeemed_at`, divided by 10,000 times the `day_count_basis`, rounded half-up to whole cents — and then summing those already-rounded per-sub-tax amounts in their posting order. The `premium_refund_cents` depends on the county: when `premium_earns_interest` is true it is the certificate's `premium_cents` plus simple interest on that premium (premium times `rate_bps` times the same face elapsed days, over 10,000 times `day_count_basis`, rounded half-up); when `premium_earns_interest` is false it is 0. Finally, when the certificate is being redeemed out of `FORECLOSURE_PENDING` with a still-filed deed application, the deed application's `deed_cost_cents` is added as a passthrough; for a plain `ACTIVE` redemption no deed cost applies. The `total_payoff_cents` is the sum of `face_payoff_cents`, `face_interest_cents`, `penalty_cents`, `sub_tax_payoff_cents`, `sub_tax_interest_cents`, `premium_refund_cents`, and any filed deed cost.

Redemption then settles the lien: it credits the holder's escrow with the payoff (the filed-deed-cost passthrough is reimbursement to the applicant and is handled outside the holder's lien credit), moves every `POSTED` subsequent tax on the certificate to `REDEEMED`, sets the parcel's `status` to `REDEEMED` and clears its `active_certificate_id` to null, and increments the certificate's `version` by one as it transitions to `REDEEMED`. When the redemption is absorbing a still-filed deed application, that deed application is also moved to `CANCELLED`. Redemptions can be listed per certificate, returning at most one row.

### 3.10. Foreclosure: Deed Application, Award, and Cancellation

If the redemption window closes without the owner paying, the holder may pursue title. The current holder — an `Investor` who must equal the certificate's `holder_investor_id` — files a **deed application**, supplying `applicant_investor_id` and the statutory `deed_cost_cents` (at least 0). The certificate must be `ACTIVE` (otherwise `ERR_INVALID_STATE`); the logical clock must have reached or passed the certificate's `redeem_deadline_at`, since an application filed before the redemption period has elapsed is rejected with `ERR_REDEMPTION_PERIOD_OPEN`; and a non-holder applicant is rejected with `ERR_NOT_CERTIFICATE_HOLDER`. Filing creates a deed application in `FILED` status, debits the holder's escrow by `deed_cost_cents`, moves the certificate from `ACTIVE` to `FORECLOSURE_PENDING`, and increments the certificate's `version`.

At filing, the application freezes a `minimum_bid_cents` — the floor price the property must fetch at the deed sale — as a snapshot of the holder's full position plus the deed cost. That position is the face amount, plus face interest accrued from `issued_at` to the filing instant (face times `rate_bps` times whole elapsed days over 10,000 times `day_count_basis`, rounded half-up), plus the flat penalty (face times `penalty_rate_bps` over 10,000, rounded half-up), plus the sum of `POSTED` sub-tax principal, plus the per-sub-tax interest (each sub-tax's principal times `sub_tax_interest_rate_bps` times whole elapsed days from its `posted_at` to the filing instant over 10,000 times `day_count_basis`, rounded half-up per sub-tax, then summed). The `minimum_bid_cents` is that position plus the `deed_cost_cents`. This value is computed once at filing and frozen on the application; it is not recomputed at award.

A `CountyTreasurer` adjudicates the filed application. **Cancelling** it moves the deed application from `FILED` to `CANCELLED` and returns the certificate from `FORECLOSURE_PENDING` back to `ACTIVE`, reopening the possibility of redemption — this is the revision loop. Cancellation requires the certificate to be `FORECLOSURE_PENDING` and the application to be `FILED`, and it increments both the deed application's `version` and the certificate's `version`. **Awarding** the deed moves the application from `FILED` to `AWARDED` and the certificate from `FORECLOSURE_PENDING` to `DEEDED`. The award names the `sale_price_cents` — the hammer price realized at the deed sale — which must be at least the frozen `minimum_bid_cents`; a price below the floor is rejected with `ERR_BID_BELOW_MINIMUM`. Award requires the certificate to be `FORECLOSURE_PENDING` and the application to be `FILED`. On award the system creates a surplus distribution, credits the holder's escrow with the lien-satisfied amount, moves every `POSTED` subsequent tax to `REDEEMED`, sets the parcel's `status` to `DEEDED` and clears its `active_certificate_id` to null, and increments both the deed application's `version` and the certificate's `version` — a transitive cascade from deed application to certificate to parcel and from deed application to surplus distribution. Deed applications can be read directly and listed per certificate, filtered by `status` or `applicant_investor_id`.

### 3.11. Surplus Distribution

When a deed is awarded for more than the lien was worth, the overage belongs to the former owner, not the certificate holder. The award creates a **surplus distribution** referencing both its `deed_application_id` and the `certificate_id`. Its `gross_proceeds_cents` equals the deed application's `sale_price_cents`. The proceeds are allocated as a waterfall: the certificate holder's bucket is filled first, so `lien_satisfied_cents` is the smaller of the gross proceeds and the frozen `minimum_bid_cents`, and the former owner's `surplus_cents` is whatever remains above the floor — the greater of 0 and the gross proceeds minus the `minimum_bid_cents`. Because award is only permitted when the price meets or exceeds the floor, the lien-satisfied amount plus the surplus always equal the gross proceeds, with the holder made whole before any overage is set aside. A new surplus distribution has `claimed` set to false. A `CountyTreasurer` records the former owner's claim, which flips `claimed` to true. Surplus distributions can be listed by deed application or by certificate, each returning at most one row.

## 4. Endpoint Definitions

Operations that create a brand-new resource — a county, a parcel, an investor, a deposit, a sale, a listing, a bid, a subsequent tax, a redemption, an assignment, or a deed application — return `201 Created`. State-transition and adjudication operations that modify an existing resource — opening, closing, settling, or withdrawing within a sale, redeeming a certificate, awarding or cancelling a deed, claiming a surplus, and advancing the clock — return `200 OK`. All read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock to a UTC instant | CountyTreasurer |
| POST | `/counties` | Create a county tax-sale configuration | CountyTreasurer |
| GET | `/counties/{countyId}` | Get a county | CountyTreasurer, Investor, Auditor |
| POST | `/counties/{countyId}/parcels` | Register a delinquent parcel | CountyTreasurer |
| GET | `/counties/{countyId}/parcels/{parcelId}` | Get a parcel | CountyTreasurer, Investor, Auditor |
| GET | `/counties/{countyId}/parcels` | List parcels in a county | CountyTreasurer, Investor, Auditor |
| POST | `/investors` | Register an investor | Investor, CountyTreasurer |
| GET | `/investors/{investorId}` | Get an investor (escrow ledger view) | Investor, CountyTreasurer, Auditor |
| POST | `/investors/{investorId}/deposits` | Fund an investor's escrow account | Investor, CountyTreasurer |
| POST | `/counties/{countyId}/sales` | Create a tax sale | CountyTreasurer |
| GET | `/counties/{countyId}/sales/{saleId}` | Get a tax sale | CountyTreasurer, Investor, Auditor |
| GET | `/counties/{countyId}/sales` | List sales in a county | CountyTreasurer, Investor, Auditor |
| POST | `/counties/{countyId}/sales/{saleId}/open` | Open a sale for bidding | CountyTreasurer |
| POST | `/counties/{countyId}/sales/{saleId}/close` | Close a sale; run the award cascade | CountyTreasurer |
| POST | `/counties/{countyId}/sales/{saleId}/settle` | Settle a closed sale | CountyTreasurer |
| POST | `/counties/{countyId}/sales/{saleId}/listings` | Attach a parcel to a sale as a listing | CountyTreasurer |
| GET | `/counties/{countyId}/sales/{saleId}/listings/{listingId}` | Get a listing | CountyTreasurer, Investor, Auditor |
| GET | `/counties/{countyId}/sales/{saleId}/listings` | List listings on a sale | CountyTreasurer, Investor, Auditor |
| POST | `/counties/{countyId}/sales/{saleId}/listings/{listingId}/withdraw` | Withdraw a listing before close | CountyTreasurer |
| POST | `/counties/{countyId}/sales/{saleId}/listings/{listingId}/bids` | Place a bid on a listing | Investor |
| GET | `/counties/{countyId}/sales/{saleId}/listings/{listingId}/bids/{bidId}` | Get a bid | CountyTreasurer, Investor, Auditor |
| GET | `/counties/{countyId}/sales/{saleId}/listings/{listingId}/bids` | List bids on a listing | CountyTreasurer, Investor, Auditor |
| GET | `/counties/{countyId}/certificates/{certificateId}` | Get a certificate | CountyTreasurer, Investor, Auditor |
| GET | `/counties/{countyId}/certificates` | List certificates in a county | CountyTreasurer, Investor, Auditor |
| GET | `/counties/{countyId}/certificates/{certificateId}/payoff-quote` | Get a non-mutating payoff quote | CountyTreasurer, Investor, Auditor |
| POST | `/counties/{countyId}/certificates/{certificateId}/redeem` | Process a redemption | CountyTreasurer |
| POST | `/counties/{countyId}/certificates/{certificateId}/sub-taxes` | Pay a subsequent year's tax | Investor |
| GET | `/counties/{countyId}/certificates/{certificateId}/sub-taxes` | List sub-taxes on a certificate | CountyTreasurer, Investor, Auditor |
| GET | `/counties/{countyId}/certificates/{certificateId}/redemptions` | List redemptions on a certificate | CountyTreasurer, Investor, Auditor |
| POST | `/counties/{countyId}/certificates/{certificateId}/assignments` | Record a certificate assignment | Investor |
| GET | `/counties/{countyId}/certificates/{certificateId}/assignments` | List assignments on a certificate | CountyTreasurer, Investor, Auditor |
| POST | `/counties/{countyId}/certificates/{certificateId}/deed-applications` | Apply for a tax deed | Investor |
| GET | `/counties/{countyId}/deed-applications/{deedApplicationId}` | Get a deed application | CountyTreasurer, Investor, Auditor |
| GET | `/counties/{countyId}/certificates/{certificateId}/deed-applications` | List deed applications on a certificate | CountyTreasurer, Investor, Auditor |
| POST | `/counties/{countyId}/deed-applications/{deedApplicationId}/award` | Award the tax deed | CountyTreasurer |
| POST | `/counties/{countyId}/deed-applications/{deedApplicationId}/cancel` | Cancel a filed deed application | CountyTreasurer |
| GET | `/counties/{countyId}/deed-applications/{deedApplicationId}/surplus` | List the surplus for a deed | CountyTreasurer, Investor, Auditor |
| GET | `/counties/{countyId}/certificates/{certificateId}/surplus` | List surplus distributions for a certificate | CountyTreasurer, Investor, Auditor |
| POST | `/counties/{countyId}/deed-applications/{deedApplicationId}/surplus/{surplusId}/claim` | Record a surplus claim | CountyTreasurer |
| GET | `/counties/parcels/{parcelId}` | Get a parcel (flat) | CountyTreasurer, Investor, Auditor |
| GET | `/counties/parcels` | List/filter parcels | CountyTreasurer, Investor, Auditor |
| GET | `/counties/sales/{saleId}` | Get a sale (flat) | CountyTreasurer, Investor, Auditor |
| GET | `/counties/sales` | List/filter sales | CountyTreasurer, Investor, Auditor |
| GET | `/counties/listings/{listingId}` | Get a listing (flat) | CountyTreasurer, Investor, Auditor |
| GET | `/counties/listings` | List/filter listings | CountyTreasurer, Investor, Auditor |
| GET | `/counties/bids/{bidId}` | Get a bid (flat) | CountyTreasurer, Investor, Auditor |
| GET | `/counties/bids` | List/filter bids | CountyTreasurer, Investor, Auditor |
| GET | `/counties/certificates/{certificateId}` | Get a certificate (flat) | CountyTreasurer, Investor, Auditor |
| GET | `/counties/certificates` | List/filter certificates | CountyTreasurer, Investor, Auditor |
| GET | `/counties/sub-taxes/{subTaxId}` | Get a subsequent-tax (flat) | CountyTreasurer, Investor, Auditor |
| GET | `/counties/sub-taxes` | List/filter sub-taxes | CountyTreasurer, Investor, Auditor |
| GET | `/counties/redemptions/{redemptionId}` | Get a redemption (flat) | CountyTreasurer, Investor, Auditor |
| GET | `/counties/redemptions` | List/filter redemptions | CountyTreasurer, Investor, Auditor |
| GET | `/counties/assignments/{assignmentId}` | Get an assignment (flat) | CountyTreasurer, Investor, Auditor |
| GET | `/counties/assignments` | List/filter assignments | CountyTreasurer, Investor, Auditor |
| GET | `/counties/deed-applications/{deedApplicationId}` | Get a deed application (flat) | CountyTreasurer, Investor, Auditor |
| GET | `/counties/deed-applications` | List/filter deed applications | CountyTreasurer, Investor, Auditor |
| GET | `/counties/surplus/{surplusId}` | Get a surplus distribution (flat) | CountyTreasurer, Investor, Auditor |
| GET | `/counties/surplus` | List/filter surplus distributions | CountyTreasurer, Investor, Auditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_CERTIFICATE_HOLDER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_BID` | 422 Unprocessable Entity |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CROSS_COUNTY_REFERENCE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SALE_NOT_DUE` | 409 Conflict |
| `ERR_SALE_EMPTY` | 409 Conflict |
| `ERR_REDEMPTION_PERIOD_OPEN` | 409 Conflict |
| `ERR_DEED_ALREADY_AWARDED` | 409 Conflict |
| `ERR_BID_BELOW_MINIMUM` | 409 Conflict |
| `ERR_DUPLICATE_SUB_TAX` | 409 Conflict |
| `ERR_INSUFFICIENT_ESCROW` | 402 Payment Required |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
