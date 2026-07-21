# House Swap Exchange API — Product Requirements Document

## 1. Introduction

The House-Swap & Home-Exchange Network is a peer-to-peer platform on which members list their homes, publish the dates those homes are available, and trade stays with one another either by paying platform points or by agreeing to a reciprocal swap. The API described here is the authoritative backend for that network: it governs member onboarding and identity verification, the points economy, the multi-round negotiation that turns a request into a binding agreement, the stay lifecycle from confirmation through completion, and the after-stay processes of damage insurance and dispute resolution.

Because two independent members — a traveling guest and a hosting owner — must reach agreement on dates, price, and terms before any home changes hands, the system is fundamentally a negotiation engine wrapped around a conserved points ledger. Every points movement is double-entry and nets to zero across the parties involved, holds are placed the moment a member commits to a priced request, and a member can never spend points they have already promised elsewhere. Trust is earned through completed exchanges and eroded by upheld damage claims and lost disputes, and that trust — together with identity verification — gates who may transact with whom. This document specifies the entities, the state machines that move them, the calculations that price and settle them, and the validation order that protects them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply across every endpoint: authentication, the response envelope, pagination, common resource fields, concurrency, the points ledger, numeric precision, the logical clock, and nested-resource validation.

### 2.1. User and Role-Based Access Control

Every request other than member self-registration must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. The system recognizes exactly three roles: `Anonymous`, `Member`, and `PlatformAdmin`. If either header is missing, or if `X-User-Role` is not one of these declared role names, the request is rejected with `ERR_UNAUTHENTICATED`. If the headers are well-formed but the role — or the specific member behind it — is not permitted to perform the operation, the request is rejected with `ERR_UNAUTHORIZED`.

When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller identifier that is not tied to any persisted entity; the `Anonymous` role may only self-register a new member and may do nothing else.

When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references a member compare that resource's owning foreign-key field to `X-User-ID`: a member may act as the requester, host, guest, home owner, claimant, or dispute opener only on resources whose corresponding member reference equals their own `X-User-ID`. An attempt to operate on another member's resource is an `ERR_UNAUTHORIZED` rejection, and for agreement party-only operations where the acting member is neither the guest nor the host, the rejection is `ERR_NOT_AGREEMENT_PARTY`.

When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `decided_by` on a `Verification` when an admin decides it, and it is the author of a dispute's `resolution_note` — but it never compares that identifier to any entity's `id`. `PlatformAdmin` is operational staff responsible for verification decisions, membership activation, the stay-start transition, damage adjudication, dispute review and resolution, manual balance adjustments, and the logical clock.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint says otherwise, list results are sorted by their `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Lifecycle Fields

Most resources — members, memberships, home listings, availability windows, verifications, exchange requests, exchange agreements, damage claims, and disputes — carry a standard set of system-managed fields: an `id` that is a server-minted UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits marking creation; an `updated_at` ISO 8601 UTC timestamp refreshed on every mutation; and a `version` integer that begins at its initial value and increments by one on each mutation.

One resource is deliberately leaner: a `PointsLedgerEntry` carries only `id` and `created_at`. Ledger entries are append-only accounting records — once written they are not mutated in place (a released hold is superseded, not edited) — so they have neither an `updated_at` field nor a `version` field.

Whenever a derived field is recomputed as a side effect of some operation — a member's balances, a member's `trust_score`, a listing's booked-versus-open night totals — the mutation refreshes the affected resource's `updated_at` and increments its `version` exactly as any other change would.

### 2.5. Optimistic Concurrency Control

Accepting an exchange request is the one write in this system guarded by optimistic concurrency control, because each acceptance books a window on a home listing and advances that listing's `version`. The accept operation requires a non-optional `expected_listing_version` field carrying the client's last observed `version` of the target `HomeListing`. If that value does not equal the listing's current `version`, the acceptance is rejected with `ERR_STALE_LISTING_VERSION` at HTTP status 412. This is a stale-view guard: when a listing's version has advanced since the requester last read it — for instance because a prior acceptance already booked one of its windows and bumped the version — a later acceptance still carrying the pre-advance version is operating on an outdated picture of the listing's availability and terms, and is refused even if it targets a different, still-open window. No other endpoint accepts or requires a version field.

### 2.6. The Points Ledger: Settled and Available Balances

All points movements are recorded as `PointsLedgerEntry` rows, each with a `member_id` naming whose balance it affects, an optional `agreement_id` linking it to the exchange that generated it (null for a welcome bonus or an administrative adjustment), an `entry_type`, a signed integer `amount` (negative for debits, positive for credits), a `status`, and a human-readable `memo`. The `entry_type` is one of `WELCOME_BONUS`, `ADMIN_ADJUSTMENT`, `EXCHANGE_HOLD`, `EXCHANGE_DEBIT`, `EXCHANGE_CREDIT`, `EXCHANGE_REFUND`, `CREDIT_REVERSAL`, `DAMAGE_SETTLEMENT`, or `DISPUTE_PENALTY`.

A ledger entry's `status` is one of `HELD`, `POSTED`, or `VOIDED`. A `HELD` entry reserves availability without affecting the realized balance; a `POSTED` entry affects the realized balance; a `VOIDED` entry is a released hold that affects nothing. From these, each member exposes two computed balances. The `settled_points_balance` is the sum of the `amount` of every `POSTED` entry for that member. The `available_points_balance` is the sum of the `amount` of every entry for that member whose status is either `POSTED` or `HELD`. Because holds are recorded as negative amounts, a member's available balance is at or below their settled balance for as long as any hold remains outstanding. The settled variant is the realized balance used for display and final accounting; the available variant is what a new priced request is checked against, so that outstanding holds cannot be spent twice. Both balances default to 0 for a brand-new member.

### 2.7. Precision, Rounding, and Point Conservation

All points quantities are integers, and every calculation that could produce a fraction resolves it by rounding half up. Where a calculation sums per-unit amounts — most importantly the per-night pricing of a stay — the rounding is applied to each unit before the units are summed; the sum is never rounded after the fact. Balance aggregation itself introduces no rounding because every stored `amount` is already an integer.

Point conservation is a system invariant: every business event that moves points between members writes offsetting entries that net to zero. A priced acceptance debits the guest and credits the host by the same magnitude; a cancellation refund credits the guest and reverses an equal amount from the host; a damage settlement debits the at-fault party and credits the other by the settled payout; and a dispute penalty debits the respondent and credits the claimant by the same points. No event ever creates or destroys points except the deliberate `WELCOME_BONUS` grant and an explicit `ADMIN_ADJUSTMENT`.

### 2.8. The Logical Clock and Lazy Expiry

The system runs on a logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-07-01T00:00:00Z`, and until an operator explicitly sets it, it stays at that value and never falls back to real time. A `PlatformAdmin` advances the clock by supplying a target instant as `to_iso8601`; the response reports the new `current_utc`. Time-based transitions are evaluated lazily against this clock. When the clock is advanced (or a resource is read), any exchange request whose `expires_at` has passed transitions to `EXPIRED`, and any active membership whose `expires_at` has passed transitions to `EXPIRED`. Every relative deadline in the system — a request's time-to-live, a membership term, the cancellation-refund windows, and the traveler double-booking buffer — is measured against this logical clock, not against real elapsed time.

### 2.9. Nested Resource Retrieval and Validation Ordering

Many endpoints address a resource through a path that names one or more parents, and some also reference resources in the body. Existence is validated left-to-right through the path and then through the body's foreign keys, and the first identifier that does not resolve produces its own not-found error: a missing member yields `ERR_MEMBER_NOT_FOUND`, a missing membership `ERR_MEMBERSHIP_NOT_FOUND`, a missing listing `ERR_LISTING_NOT_FOUND`, a missing or off-listing availability window `ERR_AVAILABILITY_WINDOW_NOT_FOUND`, a missing verification `ERR_VERIFICATION_NOT_FOUND`, a missing request `ERR_REQUEST_NOT_FOUND`, a missing agreement `ERR_AGREEMENT_NOT_FOUND`, a missing claim `ERR_CLAIM_NOT_FOUND`, and a missing dispute `ERR_DISPUTE_NOT_FOUND`.

Across the whole API the checks run in a fixed priority order, so that the reported error is always the highest-priority failure. Authentication comes first: absent or invalid headers give `ERR_UNAUTHENTICATED`. Authorization comes second: a role or ownership violation gives `ERR_UNAUTHORIZED`. Existence comes third, producing the appropriate not-found error. Body well-formedness comes fourth — required fields present, enum values legal, integers within their declared ranges — otherwise `ERR_VALIDATION`. Date-range well-formedness comes fifth, giving `ERR_INVALID_DATE_RANGE` when a date span is not strictly positive. State admissibility comes sixth, giving `ERR_INVALID_STATE` when a resource is not in a state that admits the requested transition. Only after all of these do the endpoint-specific business rules described in §3 run, and they run in the further order those subsections spell out.

## 3. Business Logic & Workflows

### 3.1. Membership, Onboarding, and Identity Verification

A new member joins by self-registering with an `email` (unique across all members and non-empty), a `full_name`, and a `home_city`. Registration is the only anonymous operation. A freshly registered member starts `UNVERIFIED` in their `verification_status`, holds no membership so their `active_membership_tier` is null, carries a `settled_points_balance` and `available_points_balance` of 0, and is seeded with a `trust_score` of 50. Their `completed_exchange_count`, `upheld_damage_count`, and `disputes_lost_count` all begin at 0. A member record can be fetched to reveal these computed balances and trust.

To transact, a member subscribes to a plan by creating a membership for themselves, naming the subscribing `member_id` and a `tier` of `BASIC`, `PLUS`, or `PREMIER`. The membership is born in `PENDING_ACTIVATION` and remains inert until a `PlatformAdmin` activates it. Activation is refused unless the membership is still `PENDING_ACTIVATION`, and it is refused with `ERR_DUPLICATE_ACTIVE_MEMBERSHIP` if the member already holds another membership in `ACTIVE` status — a member may have at most one active membership at a time. On successful activation the membership moves `PENDING_ACTIVATION → ACTIVE`, its `activated_at` is stamped with the current logical instant, its `expires_at` is set to `activated_at` plus the fixed membership term of `MEMBERSHIP_TERM_DAYS` days, and a `WELCOME_BONUS` is posted to the member — 500 points for `BASIC`, 1000 for `PLUS`, and 2000 for `PREMIER` — after which the member's settled and available balances are recomputed. When the logical clock later passes `expires_at`, an `ACTIVE` membership lazily transitions `ACTIVE → EXPIRED` with no further effect.

A member may cancel their own membership. Cancellation from `PENDING_ACTIVATION` simply voids the never-activated subscription; cancellation from `ACTIVE` ends it early but the member keeps any welcome bonus already granted. Neither cancellation moves points. Cancelling a membership that is neither `PENDING_ACTIVATION` nor `ACTIVE` is an `ERR_INVALID_STATE` rejection.

Identity and home verification run in parallel. A member submits a verification for themselves, naming the `member_id`, a `verification_type` of `IDENTITY` or `HOME`, and a `document_ref` pointing at the submitted evidence. The verification opens in `PENDING_REVIEW`. A `PlatformAdmin` decides it by supplying a `decision`; an approval moves it `PENDING_REVIEW → VERIFIED` and a rejection moves it `PENDING_REVIEW → REJECTED`, and in both cases the deciding admin's identifier is recorded in `decided_by`. Deciding a verification that is not `PENDING_REVIEW` is rejected with `ERR_INVALID_STATE`. A member's `verification_status` is `VERIFIED` exactly when they have at least one `IDENTITY` verification in `VERIFIED` status, and approving an identity verification is what flips it there; a `HOME` verification does not by itself confer verified status.

Finally, a `PlatformAdmin` may seed or correct a member's balance by posting a manual `ADMIN_ADJUSTMENT` ledger entry with a signed `amount` (which may be negative) and an optional `memo`; this posts the entry and recomputes the member's settled and available balances. A member's ledger entries and memberships can each be listed for audit.

### 3.2. Homes and Availability

A verified reputation is not required to draft a listing, but it is required to publish one. A member creates a home listing for themselves by supplying the `owner_member_id`, a `title`, an `address_city`, an `address_country`, a `points_per_night` value of at least 1, a `max_points_per_exchange` that is at least the minimum exchange floor of 100 points, a `capacity` of at least 1 guest, and optionally a `min_trust_score` between 0 and 100 that defaults to 0. The listing is created in `DRAFT`.

Before a listing can be targeted by anyone, its owner activates it, moving it `DRAFT → ACTIVE`. Activation is permitted only to the owning member, only while the listing is still `DRAFT`, and only when the owner's `verification_status` is `VERIFIED`; an unverified owner is turned away with `ERR_MEMBER_NOT_VERIFIED`. Activating the listing increments its `version` by one. Only an `ACTIVE` listing is a valid target for an exchange request.

The owner publishes bookable availability on the listing as availability windows. Each window names the parent `listing_id` and a half-open date span from an inclusive `start_date` to an exclusive `end_date`, both written as `YYYY-MM-DD`; the window covers every date from the start up to but not including the end. The window's `nights` is the number of days in that half-open span and must be at least 1, so the `end_date` must fall strictly after the `start_date` — a non-positive span is rejected with `ERR_INVALID_DATE_RANGE`. A window opens in `OPEN` status and is bookable until an acceptance consumes it, at which point it flips to `BOOKED`; the listing's open-night and booked-night totals move together so that booking a window decreases open nights and increases booked nights by that window's `nights` while the total is conserved. A single window can be fetched directly to read its status, and a listing's windows and the requests targeting or offering it can each be listed.

### 3.3. Opening an Exchange Request

A member opens an exchange request as the prospective guest by naming the `requester_member_id`, the `target_listing_id` they wish to stay in, an `exchange_type`, an inclusive `requested_start_date`, an exclusive `requested_end_date`, and — only for a reciprocal swap — the `offered_listing_id` of their own home put up in return. The `exchange_type` is `POINTS`, which debits points from the requester, or `RECIPROCAL`, which is a straight home swap whose points cost is always 0; the `offered_listing_id` is null for a points request. The requested span is half-open on the same basis as an availability window, and the `requested_end_date` must be strictly after the `requested_start_date` or the request is rejected with `ERR_INVALID_DATE_RANGE`.

Opening a request runs a battery of checks in a fixed order after the universal auth, existence, and body-shape checks. First the target listing must be `ACTIVE`, otherwise `ERR_LISTING_NOT_ACTIVE`. Next the requester must currently hold a membership in `ACTIVE` status, otherwise `ERR_MEMBERSHIP_INACTIVE`. Then the requester's `trust_score` must be at least the target listing's `min_trust_score`, otherwise `ERR_TRUST_TOO_LOW`. Finally, for a points request, the requester's `available_points_balance` must be at least the computed `points_cost` so that placing the hold leaves availability at or above zero, otherwise `ERR_INSUFFICIENT_POINTS`.

The request's `points_cost` is computed when the request is created and is 0 for any reciprocal swap. For a points request it is priced night by night across the half-open requested span. Each night is assigned a season multiplier from the calendar month of that date: 1.5 for June, July, August, and December (the peak season); 1.2 for March, April, May, September, October, and November (the shoulder season); and 1.0 for January and February (the off season). A membership discount is drawn from the requester's active tier — nothing for `BASIC` or for no active membership, ten percent for `PLUS`, and twenty percent for `PREMIER`. Each night's charge is the listing's `points_per_night` multiplied by that night's season multiplier and then by one minus the tier discount, and that per-night charge is rounded half up to a whole number of points. The rounded nightly charges are then summed across all nights — the rounding is per night and precedes the sum. The summed total is then clamped: the final cost is the larger of the 100-point minimum exchange floor and the smaller of the summed total and the target listing's `max_points_per_exchange`. On creation of a points request the system posts a `HELD` hold ledger entry reserving the negative of that cost, records that entry's id in `hold_ledger_entry_id`, sets the request's `expires_at` to the creation instant plus the fixed request time-to-live of `REQUEST_TTL_DAYS` (exactly 7) days, and recomputes the requester's available balance so the hold immediately reduces it. A reciprocal request places no hold and leaves `hold_ledger_entry_id` null. Every new request opens in `PROPOSED` status. A requester can list the requests they have opened, and a single request can be fetched to read its negotiation status and current `points_cost`.

### 3.4. The Negotiation Loop

A request is a live negotiation between the guest who opened it and the host who owns the target listing. The host may counter a `PROPOSED` request, moving it `PROPOSED → COUNTERED`; only the target listing's owner may do so and only while the request is `PROPOSED`. Countering overwrites the `requested_start_date` and `requested_end_date` with the host's proposed dates, recomputes `points_cost` from those new dates, and — for a points request — updates the amount on the outstanding `HELD` hold to the negative of the new cost, then resets `expires_at` to the current instant plus the same `REQUEST_TTL_DAYS` (exactly 7) days.

The requester answers a counter by re-proposing, moving the request `COUNTERED → PROPOSED`; only the original requester may do so and only while the request is `COUNTERED`. A re-proposal may optionally overwrite the requested dates again, recomputes `points_cost`, updates the held amount for a points request, and resets `expires_at` the same way. This loop between `PROPOSED` and `COUNTERED` can repeat as many times as the two parties need.

The negotiation ends in one of several terminal ways. The host may decline a request that is `PROPOSED` or `COUNTERED`, moving it to `DECLINED`; the requester may withdraw a request that is `PROPOSED` or `COUNTERED`, moving it to `WITHDRAWN`; and if the logical clock passes a request's `expires_at` while it is still `PROPOSED` or `COUNTERED`, it lazily transitions to `EXPIRED`. In every one of these three endings, a points request releases its reservation by voiding the `HELD` hold ledger entry — conserving the requester's points — and the requester's available balance is recomputed accordingly. Declining, withdrawing, countering, or re-proposing a request that is not in an admissible state is rejected with `ERR_INVALID_STATE`.

### 3.5. Acceptance: Sealing the Agreement

The host seals the deal by accepting a `PROPOSED` request, which moves it `PROPOSED → ACCEPTED` and brings an `ExchangeAgreement` into being. The accept payload names the chosen `availability_window_id` and the `expected_listing_version`. Only the target listing's owner may accept, and only while the request is `PROPOSED`. Acceptance is the most heavily guarded operation in the system, and after the universal checks its business rules run in this order.

Both parties must be trustworthy in identity: the guest's and the host's `verification_status` must each be `VERIFIED`, otherwise the acceptance is refused with `ERR_MEMBER_NOT_VERIFIED`. The chosen availability window must belong to the target listing and be `OPEN`, and no `BOOKED` window on that listing may overlap the requested half-open span (windows that merely abut are fine); a violation is `ERR_AVAILABILITY_CONFLICT`. The guest must not be over-committed: they may have no other non-terminal agreement whose closed stay from `check_in` to `check_out` falls within `TRAVEL_BUFFER_DAYS` (a fixed travel buffer of exactly 1 day) of this stay — two of the same guest's closed stays must be separated by strictly more than one day, so stays that overlap, abut (share an endpoint date), or sit within a single day of each other are too close and are rejected with `ERR_TRAVELER_DOUBLE_BOOKED`. Finally the optimistic-concurrency guard of §2.5 applies — `expected_listing_version` must equal the target listing's current `version`, otherwise `ERR_STALE_LISTING_VERSION` at status 412.

When all checks pass, the acceptance produces a cascade. A new `ExchangeAgreement` is created in `PENDING_CONFIRMATION`, copying the originating `request_id`, the `guest_member_id` (the requester), the `host_member_id` (the listing owner), the `listing_id` (the target listing), the booked `availability_window_id`, the `exchange_type`, the `check_in` (from the requested start date) and `check_out` (from the requested end date), and a `points_cost` snapshot taken from the request. Its `coverage_limit_points` starts at 0, its `insurance_status` at `NONE`, and its `refund_points` at 0. The chosen window flips `OPEN → BOOKED`, moving the listing's night totals as described in §3.2. For a points exchange, the `HELD` hold is voided and replaced by realized postings: an `EXCHANGE_DEBIT` of the negative points cost against the guest and an `EXCHANGE_CREDIT` of the equal positive amount to the host, after which both members' settled and available balances are recomputed. Because acceptance books a window, it also increments the target listing's `version` by one — which is precisely what makes any later acceptance carrying the now-stale version fail the concurrency guard. The acceptance returns the newly created agreement.

### 3.6. The Stay Lifecycle

An agreement travels from `PENDING_CONFIRMATION` to a terminal `COMPLETED` or `CANCELLED`. Either party — guest or host — confirms a `PENDING_CONFIRMATION` agreement, moving it `PENDING_CONFIRMATION → CONFIRMED`. Confirmation is where insurance switches on: the agreement's `coverage_limit_points` is set from the host's `active_membership_tier` at that moment — 2000 points for `BASIC`, 5000 for `PLUS`, 10000 for `PREMIER`, and 0 if the host has no active membership — and its `insurance_status` is set to `ACTIVE`. Confirming an agreement that is not `PENDING_CONFIRMATION`, or acting as someone who is neither the guest nor the host, is rejected accordingly.

Once the logical clock reaches the stay's `check_in`, a `PlatformAdmin` starts the stay, moving the agreement `CONFIRMED → IN_PROGRESS` with no other effect; starting before `check_in` or from a state other than `CONFIRMED` is refused. After the clock reaches the stay's `check_out`, either party completes the stay, moving it `IN_PROGRESS → COMPLETED`. Completion increments both the guest's and the host's `completed_exchange_count` by one and recomputes each of their `trust_score` values. A member's trust score is fifty, plus two for every completed exchange, minus ten for every upheld damage claim recorded against them, and minus fifteen for every dispute they have lost, with the result clamped to lie between 0 and 100 inclusive.

Cancellation is available only from `PENDING_CONFIRMATION` or `CONFIRMED` — never once a stay is `IN_PROGRESS` or `COMPLETED` — and either party may cancel. Cancelling releases the booked window `BOOKED → OPEN`, restoring the listing's open nights. It then computes the guest's `refund_points` from how far ahead of `check_in` the cancellation lands, measured against the logical clock: seven or more days before check-in refunds the full points cost, two to six days before refunds half of it, and fewer than two days before refunds nothing. The refund fraction is applied to the agreement's `points_cost` and rounded half up. For a points agreement the system then posts an `EXCHANGE_REFUND` of the positive refund to the guest and a `CREDIT_REVERSAL` of the equal negative amount from the host — the host retains the difference between the original cost and the refund as compensation — and recomputes both members' balances. Because the original debit, credit, refund, and reversal sum to zero, points remain conserved across the cancellation.

### 3.7. Damage Claims and Insurance

After a stay is over, an aggrieved party may file a damage claim against the other. A claim is filed on an agreement by naming the `agreement_id`, the `claimant_member_id`, and a `claimed_amount` of at least 1; a `claimed_amount` below 1 is rejected with `ERR_INVALID_CLAIM_AMOUNT`. Filing is permitted only when the underlying agreement is in `COMPLETED` status and the claimant is a party to it, otherwise `ERR_AGREEMENT_NOT_COMPLETED`. On filing, the system derives the `respondent_member_id` as the other party to the agreement — the guest if the claimant is the host, otherwise the host — computes a `provisional_payout`, and sets the agreement's `insurance_status` to `CLAIMED`. The claim opens in `FILED`.

Both the provisional payout and the eventual final payout are computed by the same formula, differing only in their input amount. A tiered deductible rate is chosen by band: an amount of 500 points or less uses a rate of twenty percent, an amount over 500 up to and including 2000 uses ten percent, and an amount above 2000 uses five percent. The deductible is the larger of the fixed floor of 50 points and the amount multiplied by that rate, rounded half up. The payout is then the amount capped at the agreement's `coverage_limit_points`, less the deductible, and never below zero — that is, the greater of zero and the smaller of the amount and the coverage limit, minus the deductible. The `provisional_payout` is computed at filing from the claimant-asserted `claimed_amount`.

A `PlatformAdmin` adjudicates a `FILED` claim by supplying a `decision` and, on approval, an `assessed_amount` of at least zero. Adjudicating a claim that is not `FILED` is rejected with `ERR_CLAIM_ALREADY_ADJUDICATED`. An approval moves the claim `FILED → SETTLED`: the admin's `assessed_amount` is recorded, and the same formula run against it produces the `final_payout` and the `deductible_points` actually applied. The settlement then posts a `DAMAGE_SETTLEMENT` debit of the negative final payout against the respondent and a `DAMAGE_SETTLEMENT` credit of the equal positive amount to the claimant, recomputes both balances, increments the respondent's `upheld_damage_count` by one, and recomputes the respondent's `trust_score`. A rejection instead moves the claim `FILED → REJECTED` and moves no points and changes no trust. Claims can be fetched individually or listed, filtered by their `agreement_id` or `claimant_member_id`.

### 3.8. Disputes

Separate from monetary damage, either party may open a dispute over an agreement — for conduct, no-shows, or other grievances. A dispute is opened by naming the `agreement_id`, the `opened_by_member_id`, a free-text `reason`, and the `penalty_points` of at least 1 that the opener seeks; a `penalty_points` value below 1 is rejected with `ERR_INVALID_CLAIM_AMOUNT`. On opening, the system derives the `respondent_member_id` as the other party — the guest if the opener is the host, otherwise the host. The dispute opens in `OPEN`.

While a dispute is still `OPEN`, its opener — and only its opener — may withdraw it by resolving with a withdrawal decision, moving it `OPEN → WITHDRAWN` with no side effects. A `PlatformAdmin` takes an open dispute under review, moving it `OPEN → UNDER_REVIEW`; reviewing or resolving a dispute that is already terminal is rejected with `ERR_DISPUTE_ALREADY_RESOLVED`. From `UNDER_REVIEW`, a `PlatformAdmin` resolves the dispute with a `decision` and an optional `resolution_note`. A resolution for the claimant moves it `UNDER_REVIEW → RESOLVED_FOR_CLAIMANT`: it posts a `DISPUTE_PENALTY` debit of the negative `penalty_points` against the respondent and a `DISPUTE_PENALTY` credit of the equal positive amount to the claimant, recomputes both balances, increments the respondent's `disputes_lost_count` by one, recomputes the respondent's `trust_score`, and records the `resolution_note`. A resolution for the respondent moves it `UNDER_REVIEW → RESOLVED_FOR_RESPONDENT`: it transfers no points and changes no trust, and only records the `resolution_note`. These two review outcomes are strict siblings — identical in every respect except that one carries the penalty transfer and trust hit and the other carries neither. Disputes can be fetched individually or listed, filtered by their `agreement_id` or `opened_by_member_id`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource, including state transitions, return `200 OK`. The request body, response body, and side effects for each endpoint are described in the §3 narratives above; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/members/register` | Register a new member | Anonymous |
| GET | `/members/{id}` | Fetch a member with computed balances and trust | Member, PlatformAdmin |
| POST | `/members/{id}/points-adjustments` | Post a manual admin balance adjustment | PlatformAdmin |
| GET | `/members/{id}/ledger-entries` | List a member's ledger entries | Member, PlatformAdmin |
| GET | `/members/{id}/memberships` | List a member's memberships | Member, PlatformAdmin |
| GET | `/members/{id}/home-listings` | List a member's home listings | Member, PlatformAdmin |
| GET | `/members/{id}/verifications` | List a member's verifications | Member, PlatformAdmin |
| GET | `/members/{id}/exchange-requests` | List requests where the member is requester | Member, PlatformAdmin |
| POST | `/memberships` | Subscribe (create a membership) | Member |
| POST | `/memberships/{id}/activate` | Activate a membership; grant welcome bonus | PlatformAdmin |
| POST | `/memberships/{id}/cancel` | Cancel a membership | Member |
| POST | `/verifications` | Submit a verification | Member |
| POST | `/verifications/{id}/decide` | Approve or reject a verification | PlatformAdmin |
| POST | `/home-listings` | Create a home listing in DRAFT | Member |
| GET | `/home-listings/{id}` | Fetch a listing | Member, PlatformAdmin |
| POST | `/home-listings/{id}/activate` | Activate a DRAFT listing | Member |
| POST | `/home-listings/{id}/availability-windows` | Publish an availability window | Member |
| GET | `/home-listings/{id}/availability-windows` | List a listing's windows | Member, PlatformAdmin |
| GET | `/home-listings/{id}/exchange-requests` | List requests targeting/offering this listing | Member, PlatformAdmin |
| GET | `/availability-windows/{id}` | Fetch an availability window | Member, PlatformAdmin |
| POST | `/exchange-requests` | Open an exchange request | Member |
| GET | `/exchange-requests/{id}` | Fetch a request | Member, PlatformAdmin |
| POST | `/exchange-requests/{id}/counter` | Host counters with new dates | Member |
| POST | `/exchange-requests/{id}/repropose` | Requester re-proposes | Member |
| POST | `/exchange-requests/{id}/accept` | Host accepts; create agreement (OCC) | Member |
| POST | `/exchange-requests/{id}/decline` | Host declines | Member |
| POST | `/exchange-requests/{id}/withdraw` | Requester withdraws | Member |
| GET | `/exchange-agreements/{id}` | Fetch an agreement | Member, PlatformAdmin |
| GET | `/exchange-agreements` | Filtered list of agreements | Member, PlatformAdmin |
| GET | `/exchange-agreements/{id}/ledger-entries` | List ledger entries tied to an agreement | Member, PlatformAdmin |
| POST | `/exchange-agreements/{id}/confirm` | Confirm; activate coverage | Member |
| POST | `/exchange-agreements/{id}/start` | Mark stay started | PlatformAdmin |
| POST | `/exchange-agreements/{id}/complete` | Complete stay | Member |
| POST | `/exchange-agreements/{id}/cancel` | Cancel; refund and release window | Member |
| POST | `/exchange-agreements/{id}/damage-claims` | File a damage claim | Member |
| GET | `/damage-claims/{id}` | Fetch a damage claim | Member, PlatformAdmin |
| GET | `/damage-claims` | Filtered list of damage claims | Member, PlatformAdmin |
| POST | `/damage-claims/{id}/adjudicate` | Adjudicate a damage claim | PlatformAdmin |
| POST | `/exchange-agreements/{id}/disputes` | Open a dispute | Member |
| GET | `/disputes/{id}` | Fetch a dispute | Member, PlatformAdmin |
| GET | `/disputes` | Filtered list of disputes | Member, PlatformAdmin |
| POST | `/disputes/{id}/review` | Take a dispute under review | PlatformAdmin |
| POST | `/disputes/{id}/resolve` | Resolve a dispute (or opener withdraw) | Member, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_MEMBERSHIP_NOT_FOUND` | 404 |
| `ERR_LISTING_NOT_FOUND` | 404 |
| `ERR_AVAILABILITY_WINDOW_NOT_FOUND` | 404 |
| `ERR_VERIFICATION_NOT_FOUND` | 404 |
| `ERR_REQUEST_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LISTING_NOT_ACTIVE` | 409 |
| `ERR_MEMBERSHIP_INACTIVE` | 409 |
| `ERR_DUPLICATE_ACTIVE_MEMBERSHIP` | 409 |
| `ERR_TRUST_TOO_LOW` | 403 |
| `ERR_INSUFFICIENT_POINTS` | 402 |
| `ERR_MEMBER_NOT_VERIFIED` | 403 |
| `ERR_AVAILABILITY_CONFLICT` | 409 |
| `ERR_TRAVELER_DOUBLE_BOOKED` | 409 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_STALE_LISTING_VERSION` | 412 |
| `ERR_AGREEMENT_NOT_COMPLETED` | 409 |
| `ERR_INVALID_CLAIM_AMOUNT` | 422 |
| `ERR_CLAIM_ALREADY_ADJUDICATED` | 409 |
| `ERR_DISPUTE_ALREADY_RESOLVED` | 409 |
| `ERR_NOT_AGREEMENT_PARTY` | 403 |
