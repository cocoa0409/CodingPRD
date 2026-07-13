# Domain Registrar & Hosting API — Product Requirements Document

## 1. Introduction

A domain registrar sits at an awkward intersection. On one side it is a registry gateway bound by ICANN-style rules — sixty-day transfer locks, EPP authorization codes, grace periods that give a lapsed name a second chance before it falls back into the pool. On the other side it is an ordinary commerce business that sells hosting plans, certificates, mailboxes, and store credit, and that must produce an invoice a finance team can reconcile to the cent. The two sides constantly interfere: a domain that expires does not merely change a flag, it silently pulls down the website hosted on it, the certificates protecting that website, and the mailboxes serving it. This document specifies the API that governs that interference.

The service we are building — mounted under `/registrar` — must therefore be honest about time, honest about money, and honest about consequences. Time is honest because the system runs on an operator-driven logical clock rather than wall-clock time, so an auditor can replay the exact sequence of events that expired a name. Money is honest because every cent that enters or leaves an account is written to an append-only ledger, and because two independently derived quantities — the credit balance and the net cash position — can always be recomputed from that ledger alone. Consequences are honest because every suspension, expiry, deletion, and transfer-out fires an explicit, specified cascade rather than leaving orphaned resources quietly serving traffic.

Three product tensions shape most of the rules that follow. First, **a quote is not a charge**: the price we show a customer for a renewal is computed against the domain's state at the instant they ask, and if the expiry ladder advances the domain between the quote and the renewal, the customer legitimately pays more. Second, **provisional is not final**: bandwidth overage shown mid-period is a running estimate that deliberately over-charges relative to the tiered figure the customer is actually billed at period close. Third, **compensation is asymmetric**: reinstating a suspended domain revives its mailboxes but never revives a revoked certificate, because a revoked certificate cannot be un-revoked in the real world either. Implementers should treat all three as intentional, not as inconsistencies to be smoothed away.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. Actors and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. `X-User-Role` must name one of exactly six declared roles — `Anonymous`, `Registrant`, `SupportAgent`, `AbuseAnalyst`, `BillingAdmin`, `PlatformAdmin`. A request whose `X-User-Role` is missing or names something outside that list is rejected with `ERR_UNAUTHENTICATED` (401), as is a request that omits `X-User-ID` while claiming any role other than `Anonymous`; `X-User-ID` is the one header an `Anonymous` caller is permitted to leave out. Once the caller is authenticated, the endpoint's own role list is consulted: a role that does not appear on the endpoint is turned away with `ERR_FORBIDDEN_ROLE` (403).

The `Registrant` role is entity-backed. When `X-User-Role` is `Registrant`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's foreign-key field to `X-User-ID`. Concretely, a `Registrant` may only act on a `Domain` whose `account_id` is their own, a `HostingSubscription` whose `account_id` is their own, an `Invoice` whose `account_id` is their own, a `TransferRequest` whose `account_id` is their own, an `AddOn` whose subscription belongs to their account, and a `DnsRecord` whose domain belongs to their account. Any other target yields `ERR_NOT_RESOURCE_OWNER` (403).

The other five roles are opaque. When `X-User-Role` is `Anonymous`, `SupportAgent`, `AbuseAnalyst`, `BillingAdmin`, or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `reviewer_user_id` or `decider_user_id` on an `AbuseReport`, where the abuse workflow writes it) but never compares it to any entity's `id`. `SupportAgent` is the read-everything, lift-suspensions operator. `AbuseAnalyst` is trust-and-safety, and is the one role subject to a segregation-of-duties rule: the analyst who takes a report into review may not be the analyst who decides it, and an attempt to do both is refused with `ERR_SEGREGATION_OF_DUTIES` (403). `BillingAdmin` owns plans, promo codes, credits, refunds, and metering periods. `PlatformAdmin` is the registry gateway and system operator — registry responses, usage ingestion, the logical clock, and the expiry sweep.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10 when the caller omits it, may be no smaller than 1, and may be no larger than 100. `offset` defaults to 0 and may be no smaller than 0. A `limit` outside the 1-to-100 window, or a negative `offset`, is a request-shape violation and is rejected with `ERR_INVALID_REQUEST` (400).

Results are always ordered by `created_at` ascending; no list endpoint offers an alternative sort. Alongside the request identifiers, the `meta` object of a list response carries `limit`, `offset`, `total_count` (the number of rows matching the filters before the window is applied) and `has_more` (true when rows remain beyond the current window).

### 2.4. Resource Identity, Timestamps and Versioning

Every resource is identified by `id`, a server-minted UUID string carrying no type prefix — the caller never supplies it. Most resources also carry the standard audit triple: `created_at` and `updated_at`, both ISO 8601 UTC timestamps rendered with three fractional digits, and `version`, an integer that begins at 1 on creation and increments by one on every mutation of that resource.

Four entities are deliberately leaner. `HostingPlan`, `InvoiceLineItem`, `LedgerEntry`, `UsageRecord` and `PromoCode` are write-once records: they carry `id` and `created_at` only. Both `updated_at` and `version` are absent from these five entity representations. A `LedgerEntry` in particular is never edited — the correction of a mistaken movement is another entry, not a rewrite.

### 2.5. The Logical Clock

The server keeps a logical clock that is the sole source of "now" for every temporal comparison in this specification — expiry, redemption ladders, certificate intervals, metering windows, transfer lock periods, and risk decay all read it. The clock's startup default is exactly `2026-05-01T00:00:00Z`; before any operator moves it, the logical clock reads that default and never falls back to the machine's wall-clock time. A `PlatformAdmin` may move the clock by supplying a `to_iso8601` instant, and the response echoes the resulting `current_utc`. Moving the clock changes no entity state on its own — the expiry ladder only advances when the sweep is run.

A "year", for term arithmetic, is exactly 365 days; there is no leap-day adjustment anywhere in the system. Ladder comparisons are made at day granularity against the logical clock and all their boundaries are inclusive: a threshold expressed as "N days after `expires_at`" is met at the instant the clock reaches that point, not only after it has passed.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded against stale reads.

A domain renewal request must carry `expected_domain_version`, a non-optional field holding the client's last observed `version` of the target `Domain`. If it does not equal the domain's current `version`, the renewal is rejected with `ERR_STALE_DOMAIN_VERSION` (HTTP 412). This guard is load-bearing because renewal is legitimately repeatable — a domain may be renewed twice, each renewal extending the term — so a second renewal replaying the version observed before the first one would pass every state precondition; only the version check catches it.

Applying a promotion to an invoice must likewise carry `expected_invoice_version`, a non-optional field holding the client's last observed `version` of the target `Invoice`. A mismatch against the invoice's current `version` is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412). Applying a promo legitimately supersedes any code applied before it, so a second application would otherwise succeed on its own merits; the version check is what stops a client that is still looking at a pre-discount view of the invoice from overwriting a discount it has never seen.

No other endpoint accepts a version field, and no other endpoint may reject a request for a version reason.

### 2.7. Money, Precision and the Ledger

All monetary amounts are integer cents. Where a rounding step is called for, the system rounds half up — a value exactly on the half-cent goes to the larger magnitude. Where and how often rounding happens is not a free choice: §3.8 pins the tax rounding to the individual line item, and §3.6 pins the two bandwidth-overage variants to different rounding orders. Two computations that differ only in rounding order will differ by a cent on many real inputs, and the specified order is the one the customer is billed at.

An account's money is derived, never stored directly. `credit_balance_cents` is the sum of `amount_cents` over that account's `LedgerEntry` rows whose `entry_type` is `CREDIT_GRANT` or `CREDIT_APPLIED`. `net_cash_cents` is the sum of `amount_cents` over that account's ledger rows whose `entry_type` is `PAYMENT` or `REFUND`. Entries are signed: a `PAYMENT` is positive (cash in), a `REFUND` is negative (cash out), a `CREDIT_GRANT` is positive, a `CREDIT_APPLIED` is negative. Each entry also records `balance_after_cents`, the account's `credit_balance_cents` immediately after that entry was written, plus a polymorphic pair — `reference_type` is `INVOICE` when the movement belongs to an invoice and `ADJUSTMENT` otherwise, and `reference_id` carries the invoice's `id` in the former case and null in the latter. Neither is a declared foreign key. Free-text `reason` is recorded on credits and refunds. Neither the credit balance nor the net cash figure is rounded; both are exact integer sums.

The cash conservation invariant follows directly: an invoice paid entirely in cash and then fully refunded to the card leaves `net_cash_cents` exactly where it stood before the payment, and leaves the invoice's `amount_paid_cents` minus `amount_refunded_cents` at zero. A refund sent to store credit deliberately does not restore `net_cash_cents` — it converts cash into `credit_balance_cents` instead.

### 2.8. Order of Rejection

When a request violates several rules at once, exactly one error is returned, and which one is not arbitrary. The checks run in a fixed ladder, and the first violated check wins.

Authentication comes first, then the endpoint's role list, then the shape of the request itself (required fields present, enum members legal, integers non-negative, `term_years` between 1 and 10 inclusive, `ttl` between 60 and 86400 inclusive, `limit` between 1 and 100 inclusive, `offset` at least 0, `priority` present when and only when `record_type` is `MX`, `mailbox_address` present when and only when `add_on_type` is `EMAIL_MAILBOX`) — a failure here is `ERR_INVALID_REQUEST` (400). Next, every resource named in the URL path must exist, validated left to right. Next, every foreign key supplied in the request body must resolve — `account_id`, `plan_id`, `primary_domain_id`, `subscription_id`, `domain_id`, and `promo_code` on the endpoints that accept them. Next comes the `Registrant` ownership check (`ERR_NOT_RESOURCE_OWNER`), then the abuse-analyst segregation-of-duties check (`ERR_SEGREGATION_OF_DUTIES`), then the two optimistic-concurrency checks of §2.6, then the account-suspension gate: a `Registrant` whose `Account.status` is `SUSPENDED` may not make any mutating request, and is refused with `ERR_ACCOUNT_SUSPENDED` (403).

Only after all of that do the domain-specific state checks and business rules run, in the order the individual workflows of §3 describe. Two orderings are called out explicitly there because they are easy to get backwards: on an outbound transfer submission the abuse hold is checked before the registrar lock, and inside the promotion engine the eligibility gate is checked before the minimum-subtotal gate.

### 2.9. Path Resolution and Not-Found Semantics

Path parameters are resolved strictly left to right, and the first unresolvable segment determines the error. Each entity has its own not-found code: `ERR_ACCOUNT_NOT_FOUND`, `ERR_DOMAIN_NOT_FOUND`, `ERR_DNS_RECORD_NOT_FOUND`, `ERR_HOSTING_PLAN_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_ADDON_NOT_FOUND`, `ERR_TRANSFER_REQUEST_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_BILLING_PERIOD_NOT_FOUND`, `ERR_ABUSE_REPORT_NOT_FOUND` and `ERR_PROMO_CODE_NOT_FOUND` — all 404. A DNS record addressed under a domain that does not exist reports the missing domain, not the missing record.

### 2.10. Cascade Discipline

The registrar's entities do not form an ownership tree; they form a web. An add-on points at both a domain and a hosting subscription, a subscription points at both a plan and a primary domain, and an invoice line item points polymorphically at whichever of those four things it bills. Consequently, a single state change can propagate several levels deep, and the propagation is specified level by level in §3.

Three rules govern every cascade. Each entity a cascade touches has its own `updated_at` refreshed and its own `version` incremented, exactly as if it had been mutated directly. A cascade is conditional: an entity that is not in the state the cascade expects is simply left untouched rather than being force-moved. And a cascade is not automatically reversible — the compensating operation restores only what the specification says it restores, which is why a reinstated domain brings its suspended mailboxes back but leaves its revoked certificates revoked forever.

The two `Domain` state dimensions are independent. `lifecycle_status` and `lock_status` live on the same row but evolve separately, gate different operations, and neither one constrains the other's value: a domain can be `ACTIVE` and `UNLOCKED`, `ACTIVE` and `LOCKED`, or `SUSPENDED` while still carrying whichever lock value it last held.

---

## 3. Business Logic & Workflows

### 3.1. Accounts, Store Credit, and the Suspension Posture

Anyone may open a registrar account by supplying a billing contact `email` — unique across accounts and non-empty — and a `company_name`, the legal registrant name that shows up in public WHOIS output whenever privacy is switched off. An optional `auto_renew_default` may be supplied at signup and defaults to true; its only job is to seed new domains, as §3.2 explains. A fresh account starts `ACTIVE` with `credit_balance_cents` at 0, `net_cash_cents` at 0, `risk_score` at 0, and `payment_method_on_file` false. `status` moves among `ACTIVE`, `SUSPENDED` and `CLOSED`, with `CLOSED` terminal, and `SUSPENDED` is the posture that gates every mutating operation the customer might attempt.

Before any money can move, a card must be attached. Attaching one means supplying a `card_token`, which the server records as `payment_method_token` and which flips the derived `payment_method_on_file` to true — that flag is true when and only when `payment_method_token` is non-null. A `BillingAdmin` may also grant store credit outright, as a goodwill gesture or an upsell incentive, by supplying `amount_cents` and a `reason`; this writes a `CREDIT_GRANT` ledger entry with `reference_type` of `ADJUSTMENT` and refreshes the account's derived credit balance. Customers, billing operators and platform operators can all page through an account's money movements, optionally filtered by `entry_type`.

Accounts are suspended by machinery, not by hand. When the abuse cascade of §3.9 pushes an account's `risk_score` to 70 or above — at or above the threshold, not strictly above it — the account transitions `ACTIVE → SUSPENDED`. That suspension is itself a cascade: every `HostingSubscription` of the account whose `status` is `ACTIVE` or `OVER_QUOTA` transitions to `SUSPENDED`, and every `Domain` of the account has its `auto_renew_enabled` forced to false, so a customer under an abuse suspension cannot quietly keep renewing.

Only a `SupportAgent` can undo this, by reinstating the account with a `reason`. A reinstatement moves the account `SUSPENDED → ACTIVE`, brings every `SUSPENDED` subscription of the account back to `ACTIVE`, and brings every `SUSPENDED` add-on of those subscriptions back to `ACTIVE` as well. What it does *not* do is lift domain suspensions: a domain suspended for abuse stays `SUSPENDED` and must be reinstated individually, one name at a time, which is exactly the deliberate friction trust-and-safety asked for.

### 3.2. Domain Search and Registration

Pricing starts before anything is persisted. A search takes a `domain_name` — the second-level label without the dot, lowercase, 1 to 63 characters drawn from letters, digits and hyphens — together with a `tld` drawn from `com`, `net`, `io` and `xyz`, and answers with the `fqdn` (the label, a dot, the TLD), whether the name is `available`, whether it `is_premium`, and its `base_year_price_cents`. Availability is the negative of the uniqueness rule: an `fqdn` is taken while some `Domain` holds it with a `lifecycle_status` other than `DELETED` and other than `TRANSFERRED_OUT`. Names that have been deleted or transferred away release their `fqdn` back into the pool.

The price of one year is a two-step calculation with no entity state involved. The base year price is the TLD's list price — 1199 cents for a `com`, 1499 cents for a `net`, 3999 cents for an `io`, and 199 cents for an `xyz` — multiplied by five if the name is premium, and left alone otherwise. A name is premium when and only when its `domain_name` label is at most three characters long, which is what `is_premium` records. A three-letter `io` therefore lists at 19995 cents; a four-letter `io` lists at 3999.

Registration is a `Registrant` operation. It takes an `account_id`, the `domain_name` and `tld`, a `term_years` between 1 and 10 inclusive, the WHOIS contact pair `registrant_name` and `registrant_email`, and two optional switches: `whois_privacy` and `auto_renew`. When `auto_renew` is omitted, the account's `auto_renew_default` is copied into the new domain's `auto_renew_enabled`; when it is supplied it wins. `whois_privacy` seeds `whois_privacy_enabled` and defaults to false. If the requested `fqdn` is already held by a live domain, the request is refused with `ERR_DOMAIN_UNAVAILABLE`.

Registration does not produce a live domain. It produces a `Domain` sitting in `PENDING_PAYMENT` on its lifecycle dimension and `LOCKED` on its lock dimension, with `registered_at`, `expires_at` and `epp_auth_code` all still null, and alongside it an `ISSUED` invoice. That invoice carries a `DOMAIN_REGISTRATION` line whose `quantity` is the number of years and whose `unit_price_cents` is the base year price; when privacy was requested it also carries a `PRIVACY_FEE` line of 999 cents per year of the term. Only when that invoice is paid does the domain come to life: `PENDING_PAYMENT → ACTIVE`, with `registered_at` stamped to the logical clock at payment, `expires_at` set to `registered_at` plus `term_years` times 365 days, and a freshly server-minted sixteen-character `epp_auth_code`. The lock dimension is untouched and stays at its initial `LOCKED`.

Reading a domain gives different answers to different callers. A `Registrant` who owns it, a `SupportAgent` or a `PlatformAdmin` sees everything, including the `epp_auth_code`. Every other role sees `epp_auth_code` as null. And an `Anonymous` caller sees the public WHOIS projection: when `whois_privacy_enabled` is true, `registrant_name` reads `REDACTED FOR PRIVACY` and `registrant_email` reads `privacy@proxy.example`. Domains can also be listed, filtered by `account_id`, by `lifecycle_status`, or by `lock_status`.

### 3.3. Domain Settings: Privacy, Auto-Renew, and the Registrar Lock

The settings surface takes three optional switches — `whois_privacy`, `auto_renew` and `locked` — and any combination of them may be sent in one request. All three require the domain's `lifecycle_status` to be `ACTIVE`; attempting them on a domain in any other lifecycle state is refused with `ERR_INVALID_DOMAIN_STATE`. Whatever else the request does, it increments the domain's `version`.

Turning privacy on is not free. Enabling `whois_privacy` raises a new `ISSUED` invoice carrying a `PRIVACY_FEE` line of 999 cents for each remaining whole year of the term. Turning `auto_renew` on or off simply writes `auto_renew_enabled` and costs nothing.

The `locked` switch drives the domain's second, independent state dimension, which starts at `LOCKED` the moment the domain is created and cycles freely between `LOCKED` and `UNLOCKED` thereafter without ever touching `lifecycle_status`. Sending `locked` as false moves `LOCKED → UNLOCKED`; sending it as true moves `UNLOCKED → LOCKED`. Re-locking is unconditional apart from the `ACTIVE` lifecycle requirement. Unlocking is not: a name may not leave the lock before sixty days have elapsed since its `registered_at` — the logical clock must have reached at least `registered_at` plus 60 days — and an attempt to unlock inside that window is refused with `ERR_TRANSFER_LOCK_PERIOD`. This is the anti-hijacking measure that ICANN imposes on freshly registered names, and §3.7 shows it biting a second time at transfer-out.

### 3.4. Renewal, Expiry, and the Redemption Ladder

A customer can ask what a renewal would cost before committing to it. The quote takes a `term_years` and returns a read-only projection — nothing is persisted, no invoice is raised — reporting back the `domain_id`, the `term_years` asked for, the `variant` that was evaluated, the `lifecycle_status` the domain was in at quote time, the `renewal_subtotal_cents`, the `redemption_fee_cents`, the `privacy_fee_cents`, the `quoted_total_cents`, and the `quoted_at` instant the quote was taken from the logical clock. The renewal itself is the charging counterpart of the same calculation, and it is where an invoice appears.

Both variants read the same three ingredients from the domain **as it stands at the moment they run**. The renewal subtotal is the base year price of §3.2 — same TLD list price, same five-times premium multiplier — multiplied by the requested number of years. A redemption fee of 8000 cents is added when, and only when, the domain's `lifecycle_status` is `REDEMPTION` at that instant; otherwise it is zero. A privacy fee of 999 cents per requested year is added when `whois_privacy_enabled` is true; otherwise it is zero. The charge subtotal is the sum of those three figures, and it is that subtotal — before tax and before any service fee — that the quote reports as `quoted_total_cents` and that the renewal turns into invoice lines.

Because both runs read the domain live, a quote and a renewal can legitimately disagree. Consider a domain that is `EXPIRED` when the customer asks for a quote and that the sweep pushes into `REDEMPTION` before the customer acts on it: the charged subtotal then exceeds the quoted total by exactly 8000 cents, because the redemption fee that was absent at quote time is present at renewal time. That is the specified behaviour, not a defect.

The new term end depends on the branch. From `ACTIVE`, renewal **extends**: `expires_at` becomes the old `expires_at` plus the requested years times 365 days, and the domain stays `ACTIVE`. From `EXPIRED` or from `REDEMPTION`, renewal **resets**: `expires_at` becomes the logical clock now plus the requested years times 365 days — the lapsed remainder of the old term is not credited back — and the domain returns to `ACTIVE`. Both revival branches also switch `serving_enabled` back to true on every DNS record of the zone. The `EXPIRED → ACTIVE` grace renewal raises an `ISSUED` invoice with a `DOMAIN_RENEWAL` line and no redemption line; the `REDEMPTION → ACTIVE` restore raises an `ISSUED` invoice with a `DOMAIN_RENEWAL` line *and* a `REDEMPTION_FEE` line of 8000 cents. Every renewal increments the domain's `version`.

Renewal is refused outright when the domain's `lifecycle_status` is anything other than `ACTIVE`, `EXPIRED` or `REDEMPTION` — a `PENDING_PAYMENT`, `SUSPENDED`, `PENDING_DELETE`, `DELETED` or `TRANSFERRED_OUT` name yields `ERR_DOMAIN_NOT_RENEWABLE`, and the same rule guards the quote. Renewal is also bounded: the term may not be pushed more than ten years past the logical clock. If the prospective new `expires_at` minus the clock now would exceed 10 times 365 days, the request is refused with `ERR_MAX_TERM_EXCEEDED`. And, as §2.6 sets out, the renewal must carry an `expected_domain_version` equal to the domain's current `version` or it dies with `ERR_STALE_DOMAIN_VERSION`.

**The sweep.** Nothing expires on its own. A `PlatformAdmin` runs the expiry sweep, which walks every domain whose `lifecycle_status` is `ACTIVE`, `EXPIRED`, `REDEMPTION` or `PENDING_DELETE` in `created_at` ascending order — never by `id` — and applies the following ladder repeatedly to each domain, so a clock parked far in the future can carry one name from `ACTIVE` all the way to `DELETED` inside a single call.

A domain that is `ACTIVE` and whose `expires_at` has been reached by the clock takes one of two branches. If its `auto_renew_enabled` is true *and* its account is `ACTIVE` *and* that account has a payment method on file, the domain auto-renews for exactly one year: `expires_at` advances by 365 days from its previous value (the extend branch), the domain stays `ACTIVE`, its `version` increments, and an `ISSUED` invoice with a one-year `DOMAIN_RENEWAL` line is raised and immediately settled exactly as if the customer had paid it — credit first, then the card. If any one of those three conditions fails, the domain instead goes `ACTIVE → EXPIRED`, and that transition fires the outage cascade: every `DnsRecord` of the zone has `serving_enabled` set to false, every `HostingSubscription` whose `primary_domain_id` is this domain and whose `status` is `ACTIVE` or `OVER_QUOTA` transitions to `SUSPENDED`, and — as a consequence of those subscription suspensions — every `AddOn` of those subscriptions whose `status` is `ACTIVE` transitions to `SUSPENDED`.

The rest of the ladder is pure timekeeping, measured from `expires_at`. Once the clock reaches `expires_at` plus 30 days of grace, an `EXPIRED` domain drops to `REDEMPTION`; no further cascade fires, because the outage already happened on the way into `EXPIRED`. Once the clock reaches `expires_at` plus 60 days — the 30-day grace plus a 30-day redemption window — a `REDEMPTION` domain drops to `PENDING_DELETE`, and its `auto_renew_enabled` is forced to false. Once the clock reaches `expires_at` plus 65 days — those 60 plus a final 5-day pending-delete window — the domain reaches `DELETED`, which is terminal and fires the heaviest cascade of all: every `AddOn` whose `domain_id` is this domain and whose `status` is `PENDING_VALIDATION`, `ACTIVE` or `SUSPENDED` transitions to `CANCELLED`; because those mailbox add-ons have left the committed set, every affected subscription's `storage_committed_mb` is recomputed; every `HostingSubscription` whose `primary_domain_id` is this domain transitions to `CANCELLED`; and the `fqdn` is released back into the pool for anyone to register.

The same sweep does two other jobs. Every `AddOn` whose `status` is `ACTIVE` and whose `ends_at` has been reached by the clock transitions to `EXPIRED` — and if it is a mailbox, its `storage_mb_quota` leaves the subscription's committed set. Then every affected account's `risk_score` is refreshed so that time decay is applied. The sweep reports what it did: `auto_renewed_count`, `expired_count`, `redemption_count`, `pending_delete_count`, `deleted_count` and `addon_expired_count`.

### 3.5. DNS Zones, Certificates, and Mailboxes

A zone's records live under their domain. Creating one requires the domain to be `ACTIVE` — otherwise `ERR_INVALID_DOMAIN_STATE` — and takes a `record_type` from `A`, `AAAA`, `CNAME`, `MX`, `TXT` and `NS`, a `name` (the label relative to the zone, such as `@`, `www` or `_acme-challenge`), a `value` holding the IP, hostname or TXT payload, an optional `ttl` in seconds that defaults to 3600 and must lie between 60 and 86400 inclusive, and an optional `priority`. `priority` is the MX preference: it is required when `record_type` is `MX` and must be absent otherwise, and getting that pairing wrong is an `ERR_INVALID_REQUEST`. Each record also carries a derived `serving_enabled`, which is false while the parent domain's `lifecycle_status` is any of `SUSPENDED`, `EXPIRED`, `REDEMPTION`, `PENDING_DELETE`, `DELETED` or `TRANSFERRED_OUT`, and true otherwise. Records can be listed per zone and filtered by `record_type`, and deleting one likewise requires an `ACTIVE` domain.

Deletion has one referential guard. A `TXT` record may not be removed while some `AddOn` on the same domain, of `add_on_type` `SSL_CERT` and with `status` `PENDING_VALIDATION` or `ACTIVE`, has a `validation_token` equal to that record's `value` — pulling that record would strand a certificate that still depends on it, so the delete is refused with `ERR_DNS_RECORD_IN_USE`.

**Buying an add-on.** Both certificates and mailboxes are `AddOn` rows, and both are bought the same way: the buyer names a `subscription_id`, a `domain_id`, an `add_on_type`, a `term_days` between 1 and 730 inclusive, and optionally a `starts_at` (defaulting to the logical clock at creation), a `mailbox_address` and a `storage_mb_quota`. The validity window ends at `ends_at`, which is `starts_at` plus `term_days` days. The subscription must be in `ACTIVE` or `OVER_QUOTA` — anything else is `ERR_SUBSCRIPTION_NOT_ACTIVE` — and the domain must be `ACTIVE`, or the request draws `ERR_INVALID_DOMAIN_STATE`. Every add-on raises its own `ISSUED` invoice with a matching `SSL_CERT` or `EMAIL_MAILBOX` line, priced at the add-on's `unit_price_cents`.

The two types then diverge sharply, and the divergence is the point.

A **certificate** (`add_on_type` of `SSL_CERT`) is created in `PENDING_VALIDATION` with a server-minted `validation_token`; `mailbox_address` must be absent and `storage_mb_quota` is forced to 0, so a certificate never consumes storage. Its `unit_price_cents` is 0 when the subscription's plan has `included_ssl` true, and 5999 cents when the plan does not include SSL. Certificates on the same domain may not crowd each other: the new certificate's closed interval from `starts_at` to `ends_at`, widened by one buffer day on each side, must not intersect the interval of any other `SSL_CERT` add-on on that domain whose `status` is `PENDING_VALIDATION` or `ACTIVE`. Concretely, a conflict exists when such a certificate's `starts_at` is at or before the new certificate's `ends_at` plus one day *and* its `ends_at` is at or after the new certificate's `starts_at` minus one day; an intersection on either end, including bare adjacency where the new window begins exactly where an old one ended, draws `ERR_SSL_INTERVAL_CONFLICT`. Certificates that have reached `EXPIRED`, `REVOKED` or `CANCELLED` free their interval and are ignored by this check.

A certificate does not protect anything until DNS-01 validation succeeds. The owner publishes a `TXT` record on the certificate's domain, named `_acme-challenge`, whose `value` equals the certificate's `validation_token`, and then asks the system to validate. Validation requires the add-on to be an `SSL_CERT` in `PENDING_VALIDATION` — otherwise `ERR_ADDON_NOT_PENDING_VALIDATION` — and the domain to be `ACTIVE`. If no such `TXT` record is found, validation fails with `ERR_DNS_VALIDATION_FAILED`. When it is found, the certificate moves `PENDING_VALIDATION → ACTIVE`.

A **mailbox** (`add_on_type` of `EMAIL_MAILBOX`) skips validation entirely: it is born straight into `ACTIVE`. It requires a `mailbox_address` — the local part of the address — and a `storage_mb_quota`, and its `unit_price_cents` is 399 cents for each whole or partial gigabyte of that quota, taking the quota in megabytes divided by 1024 and rounding that quotient *up* to the next whole number. A 512 MB mailbox therefore costs 399 cents; a 1024 MB mailbox costs 399 cents; a 1025 MB mailbox costs 798. The pair of `domain_id` and `mailbox_address` must be unique among mailbox add-ons whose `status` is anything other than `CANCELLED`; a collision is `ERR_MAILBOX_ADDRESS_TAKEN`.

**Storage is a conserved quantity.** A subscription's `storage_committed_mb` is at all times the sum of `storage_mb_quota` over that subscription's mailbox add-ons whose `status` is `PENDING_VALIDATION`, `ACTIVE` or `SUSPENDED`. Certificates never contribute, because their quota is forced to zero. Admission is checked before the mailbox is created: if the subscription's current `storage_committed_mb` plus the requested `storage_mb_quota` would come out strictly greater than the plan's `storage_quota_mb`, the mailbox is refused with `ERR_STORAGE_QUOTA_EXCEEDED` — landing exactly on the quota is allowed. Creation adds the quota to the committed total; cancelling the mailbox subtracts exactly the same figure back out, so a create-then-cancel pair leaves the number precisely where it started. A *suspended* mailbox still holds its reservation; one that has become `EXPIRED`, `CANCELLED` or `REVOKED` does not.

Cancelling an add-on is a `Registrant` action, permitted from `PENDING_VALIDATION`, `ACTIVE` or `SUSPENDED`, and it lands the add-on in `CANCELLED` — releasing the storage reservation when it is a mailbox. Add-ons can be read individually (the response exposes `validation_token` and the `starts_at`-to-`ends_at` window) and listed with filters on `subscription_id`, `domain_id`, `add_on_type` and `status`.

### 3.6. Hosting Plans, Subscriptions, Metering, and Overage

A `BillingAdmin` defines the catalogue. Each `HostingPlan` carries a unique `plan_code`, a marketing `tier` of `STARTER`, `DELUXE` or `ULTIMATE`, a `storage_quota_mb` that is the hard cap enforced against a subscription's committed storage, a `bandwidth_quota_mb` included in each billing period before overage bites, a `monthly_price_cents` billed once at subscription creation, an `included_mailboxes` count that is purely informational and is never enforced (the storage quota is the enforced limit), an `included_ssl` flag that zeroes the price of certificates on the plan, and an `overage_rate_cents_per_gb` that anchors the bandwidth overage curve.

A customer buys a plan by naming an `account_id`, a `plan_id`, and optionally a `primary_domain_id` — the site's primary domain, which may be left null. The subscription is created in `PROVISIONING` with an `auto_renew` flag that defaults to true and is purely informational in this system (the plan is billed once at creation), alongside an `ISSUED` invoice carrying a `HOSTING_PLAN` line priced at the plan's `monthly_price_cents`. Paying that invoice moves the subscription `PROVISIONING → ACTIVE`, increments its `version`, and opens its first `BillingPeriod` — `period_start` at the logical clock now, `period_end` thirty days later, `status` `OPEN`. Subscriptions can be read (the representation exposes `storage_committed_mb` and `bandwidth_used_mb`) and listed with filters on `account_id`, `plan_id`, `primary_domain_id` and `status`.

Further metering windows are opened by a `BillingAdmin` against a subscription in `ACTIVE` or `OVER_QUOTA`, supplying a `period_start` and a `period_end`. A period is a half-open interval — its start is inclusive, its end exclusive — and two periods of the same subscription may abut exactly, with a new `period_start` equal to an existing `period_end`, but may not overlap by so much as an instant. A conflict exists when some existing period of that subscription has a `period_start` strictly before the new `period_end` *and* the new `period_start` is strictly before that period's `period_end`, and it is refused with `ERR_BILLING_PERIOD_OVERLAP`. Both `OPEN` and `CLOSED` periods occupy the timeline for this purpose. Periods can be listed per subscription, filtered by `status`.

**Ingesting usage.** A `PlatformAdmin` feeds bandwidth in, one `UsageRecord` at a time, each naming a `metric` (only `BANDWIDTH_MB` exists), an `amount_mb` of at least zero, and a `recorded_at` instant. Usage may be back-dated — late-arriving telemetry is normal — but `recorded_at` must fall inside an `OPEN` billing period of that subscription, or the record is refused with `ERR_USAGE_OUTSIDE_PERIOD`. The subscription must itself be `ACTIVE` or `OVER_QUOTA`, else `ERR_SUBSCRIPTION_NOT_ACTIVE`. After each ingest the subscription's `bandwidth_used_mb` is recomputed as the sum of `amount_mb` over the records falling inside the open period, and the period's `provisional_overage_cents` is refreshed. If, after the ingest, `bandwidth_used_mb` is *strictly greater* than the plan's `bandwidth_quota_mb`, the subscription moves `ACTIVE → OVER_QUOTA`; usage landing exactly on the quota leaves it `ACTIVE`.

**The two overage figures.** Both variants read exactly the same rows — the usage records of the period — and differ only in rate curve and rounding order.

The *provisional* figure, refreshed on every ingest and written to `provisional_overage_cents`, walks the period's records in `recorded_at` ascending order, breaking ties by `created_at` ascending, and burns down a running remaining quota that starts at the plan's `bandwidth_quota_mb`. For each record, the portion above the remaining quota is the record's `amount_mb` minus that remaining quota, floored at zero; the remaining quota is then reduced by the record's `amount_mb`, floored at zero. Each record's over-portion is converted to gigabytes by dividing by 1024, multiplied by the plan's flat `overage_rate_cents_per_gb`, **rounded half up to whole cents at that point**, and only then added to the running provisional total. No tier discount applies. Because it rounds once per record and never gives a tier break, the provisional figure over-charges relative to the final one whenever the excess crosses a tier boundary or the per-record fractions round upward — it is an estimate, and it is deliberately the pessimistic one.

The *final* figure is computed once, at period close, and written to `final_overage_cents`. It sums `amount_mb` across all the period's records first, subtracts the plan's `bandwidth_quota_mb` from that total, floors the difference at zero, and divides by 1024 to get the excess in gigabytes. That excess is then split across three tiers: the first 10 GB, the next 40 GB (that is, the portion of the excess above 10 GB and up to 50 GB), and everything beyond 50 GB. The first tier is charged at the plan's full `overage_rate_cents_per_gb`; the second tier at three-quarters of that rate; the third tier at half of it. The three tier charges are added together and the sum is **rounded half up to whole cents exactly once**, at the very end. This — not the provisional figure — is what the customer is billed.

**Closing a period.** A `BillingAdmin` closes an `OPEN` period; closing one that is already `CLOSED` yields `ERR_PERIOD_ALREADY_CLOSED`. The close computes the final overage and stores it in `final_overage_cents`, which is null for as long as the period stays `OPEN`. When that figure is greater than zero, an `ISSUED` invoice is raised with its `billing_period_id` pointing at the closed period and a single `BANDWIDTH_OVERAGE` line for the amount. The close then resets the subscription's `bandwidth_used_mb` to zero, restarting the quota baseline, and if the subscription was sitting in `OVER_QUOTA` it returns to `ACTIVE` — the `ACTIVE → OVER_QUOTA → ACTIVE` cycle repeats once per billing period.

Subscriptions are also moved by forces outside themselves. A subscription in `ACTIVE` or `OVER_QUOTA` transitions to `SUSPENDED` when its account is auto-suspended or when its primary domain enters `EXPIRED` or `SUSPENDED`, and that suspension carries every `ACTIVE` add-on of the subscription down to `SUSPENDED` with it. A `SUSPENDED` subscription returns to `ACTIVE` only through an account reinstatement, which likewise brings its `SUSPENDED` add-ons back to `ACTIVE`. And a subscription in `ACTIVE` or `SUSPENDED` whose primary domain reaches `DELETED` or `TRANSFERRED_OUT` transitions to `CANCELLED` — the terminal state — cancelling every add-on of that subscription in `PENDING_VALIDATION`, `ACTIVE` or `SUSPENDED`, and (on the deletion path) recomputing `storage_committed_mb` down to zero.

### 3.7. Transfers and the EPP Negotiation Cycle

A transfer is opened by a `Registrant` supplying an `account_id`, a `direction` of `IN` or `OUT`, the `domain_name` and `tld` of the name in question, an `epp_auth_code`, and — for an outbound move — the `domain_id` of the domain being sent away. For an inbound move `domain_id` starts null and is filled in only if and when the registry approves, at which point it points at the newly created domain. The request is born in `INITIATED` with `attempt_count` at 0 and `rejection_reason` null; an inbound request whose target `fqdn` is already held by a live domain is refused at this point with `ERR_DOMAIN_UNAVAILABLE`. Requests can be read individually and listed, filtered by `account_id`, `domain_id` and `status`.

Submission is where the gauntlet runs. Submitting requires the request to be `INITIATED` — from any other state the answer is `ERR_TRANSFER_INVALID_STATE` — and the acting account to be `ACTIVE`. An inbound submission re-checks that no live domain holds the `fqdn` and otherwise passes. An outbound submission is checked in a strict order, because several of these guards can fire at once on the same request and only the first matters.

First: the domain must be `ACTIVE` with no abuse suspension recorded in `suspension_reason`. Second — **and this is checked before the lock** — the domain must be free of any abuse hold: a `suspension_reason` of `ABUSE`, or *any* `AbuseReport` on that domain whose `status` is `UNDER_REVIEW` or `UPHELD`, blocks the transfer with `ERR_ABUSE_HOLD_ACTIVE`. A name under investigation cannot be spirited away to another registrar while trust-and-safety is still looking at it, and putting this check ahead of the lock check means an abuse hold surfaces as itself rather than being masked by an incidental lock. Third: the domain's `lock_status` must be `UNLOCKED`, or the answer is `ERR_DOMAIN_LOCKED`. Fourth: the sixty-day post-registration lock period of §3.3 applies here too — a name still inside 60 days of its `registered_at` cannot be transferred out, and the refusal is `ERR_TRANSFER_LOCK_PERIOD`. Fifth: the `epp_auth_code` on the request must equal the domain's own `epp_auth_code`, or the answer is `ERR_EPP_AUTH_MISMATCH`. A submission that clears all five moves the request `INITIATED → PENDING_ACK` and increments `attempt_count` by one.

The registry then answers, through a `PlatformAdmin` acting as the registry simulator, with an `outcome` of `APPROVED` or `REJECTED` and an optional `reason`. The request must be `PENDING_ACK`, or the answer is `ERR_TRANSFER_INVALID_STATE`.

An approval on an inbound request moves it `PENDING_ACK → COMPLETED` and mints a brand-new `Domain` owned by the request's `account_id`: `lifecycle_status` `ACTIVE`, `lock_status` `LOCKED`, `registered_at` at the logical clock now, `expires_at` at now plus 365 days, a freshly minted `epp_auth_code`, and the request's `domain_id` pointed at it. An approval on an outbound request likewise moves the request `PENDING_ACK → COMPLETED`, and the referenced domain goes `ACTIVE → TRANSFERRED_OUT` — a terminal lifecycle state — with the full departure cascade: `auto_renew_enabled` forced to false, `serving_enabled` set to false on every DNS record of the zone, every add-on of the domain whose `status` is `PENDING_VALIDATION`, `ACTIVE` or `SUSPENDED` transitioned to `CANCELLED`, and every `HostingSubscription` whose `primary_domain_id` is that domain transitioned to `CANCELLED`. The `fqdn` becomes available for registration again.

A rejection is where the cycle lives. When the registry rejects while `attempt_count` is still below the ceiling of three attempts, the request moves `PENDING_ACK → REJECTED` and stores the registry's `reason` in `rejection_reason`. The `Registrant` may then retry, supplying a fresh `epp_auth_code`: the request moves `REJECTED → INITIATED`, the new code replaces the old one, `rejection_reason` is cleared back to null, and the whole submission gauntlet can be run again. Retrying from any state other than `REJECTED` is `ERR_TRANSFER_INVALID_STATE`, and retrying once `attempt_count` has reached three is refused with `ERR_TRANSFER_MAX_ATTEMPTS`. When the registry rejects a request whose `attempt_count` has already reached three, the request does not become `REJECTED` at all — it goes straight to `FAILED`, which is terminal and cannot be retried, with the `reason` recorded in `rejection_reason`. The negotiation loop `INITIATED → PENDING_ACK → REJECTED → INITIATED` is therefore bounded at three attempts, and its two exits are `COMPLETED` and `FAILED`.

### 3.8. Invoices, Promotions, Payment, and Refunds

Nothing in this system creates an invoice by hand. Invoices appear as side effects — of a registration, a privacy toggle, a renewal (manual or automatic), a hosting purchase, an add-on purchase, and a billing-period close — and each is born `ISSUED` with `discount_cents` and `service_fee_cents` at 0, `applied_promo_code` null, `amount_paid_cents` and `amount_refunded_cents` at 0, and a `billing_period_id` that is set only on the bandwidth-overage invoice raised at a period close and is null on every other invoice. An invoice is read with its computed money fields, listed with filters on `account_id`, `status` and `billing_period_id`, and its lines can be paged.

Each `InvoiceLineItem` belongs to exactly one invoice, named by its `invoice_id`, and records an `item_type` — one of `DOMAIN_REGISTRATION`, `DOMAIN_RENEWAL`, `REDEMPTION_FEE`, `PRIVACY_FEE`, `HOSTING_PLAN`, `SSL_CERT`, `EMAIL_MAILBOX` and `BANDWIDTH_OVERAGE` — together with a `reference_id`, the polymorphic identifier of whatever is being billed (a domain, a subscription, an add-on or a billing period, resolved by the `item_type`, and not a declared foreign key), a human-readable `description`, a `quantity` (years for domain lines, 1 otherwise), and a `unit_price_cents`. From those, `line_subtotal_cents` is the exact integer product of `quantity` and `unit_price_cents` with no rounding whatsoever, `line_discount_cents` starts at 0, `line_tax_cents` is the taxed portion, and `line_total_cents` is the line subtotal less the line discount plus the line tax.

**Applying a promotion.** A `BillingAdmin` mints promo codes, each with a case-sensitive `code`, a `discount_type` of `PERCENT` or `FLAT`, a `discount_value` (for `PERCENT`, a fraction greater than zero and at most one; for `FLAT`, a whole number of cents), an `applies_to_item_types` array naming the line-item kinds it discounts, a `min_subtotal_cents` floor that defaults to 0, and a `max_discount_cents` hard cap. Applying a code to an `ISSUED` invoice — an invoice in any other status is `ERR_INVOICE_NOT_PAYABLE` — takes the `promo_code` and, per §2.6, an `expected_invoice_version`. A second application legitimately replaces the first: `applied_promo_code` is overwritten and the discount recomputed from scratch. The invoice's `version` increments.

The evaluation order of the promotion engine is pinned, and evaluating these steps in any other order gives a different answer. **One:** the invoice's pre-discount `subtotal_cents` is the sum of `line_subtotal_cents` across *all* lines. **Two:** the eligible lines are those whose `item_type` appears in the code's `applies_to_item_types`, and the eligible subtotal is the sum of their line subtotals; if there are no eligible lines, or the eligible subtotal is zero, the request is refused with `ERR_PROMO_NOT_APPLICABLE`. Only then — **three** — is the minimum gate applied, against the *pre-discount* whole-invoice subtotal: if `subtotal_cents` is below the code's `min_subtotal_cents`, the answer is `ERR_PROMO_MIN_NOT_MET`. **Four:** the raw discount is, for a `PERCENT` code, the eligible subtotal multiplied by `discount_value` and rounded half up to whole cents; for a `FLAT` code, the smaller of `discount_value` and the eligible subtotal. **Five:** the invoice's `discount_cents` is the smaller of that raw discount and the code's `max_discount_cents`. **Six:** the discount is allocated across the eligible lines as a waterfall, taking them in `created_at` ascending order and giving each line the smaller of the remaining undistributed discount and that line's own `line_subtotal_cents`, until the discount is exhausted. Ineligible lines receive a `line_discount_cents` of zero.

**Seven — the service fee.** The processing fee is keyed on the invoice's subtotal *after* the discount — that is, `subtotal_cents` minus `discount_cents` — and never on the pre-discount figure, and the fee itself never enters the discount base. When that post-discount subtotal is below 5000 cents, `service_fee_cents` is 0. When it is at least 5000 cents but below 20000 cents, `service_fee_cents` is 299. When it is 20000 cents or more, `service_fee_cents` is 999.

**Eight — tax and the total.** Tax is charged at 8.25 percent and **the rounding happens per line item, before summing**. For each line, `line_tax_cents` is the line's subtotal minus its discount, multiplied by 0.0825, rounded half up to whole cents. The invoice's `tax_cents` is the sum of those already-rounded per-line figures — it is emphatically *not* the whole-invoice discounted base multiplied by the rate and rounded once, and the two orders differ by a cent on many real invoices. The service fee is added after tax and is itself untaxed. The invoice's `total_cents` is therefore `subtotal_cents` minus `discount_cents` plus `service_fee_cents` plus `tax_cents`. Every invoice runs this same total calculation at creation (with a zero discount) and re-runs it whenever a promotion is applied.

**Paying.** Payment is available to the owning `Registrant` and to a `BillingAdmin`, on an `ISSUED` invoice only — anything else is `ERR_INVOICE_NOT_PAYABLE` — and against an `ACTIVE` account. It takes one optional switch, `use_credit`. The waterfall is credit first, then cash: the applied credit is the smaller of the account's `credit_balance_cents` and the invoice's `total_cents` when `use_credit` is on, and zero when it is not; the cash remainder is the invoice total less that applied credit. If the cash remainder is greater than zero, the account must have a payment method on file — if it does not, the payment is refused with `ERR_PAYMENT_METHOD_REQUIRED` (402). A cash remainder of exactly zero, where store credit covered the whole invoice, requires no card at all; this boundary is deliberate.

A successful payment writes a `CREDIT_APPLIED` ledger entry for the negative of the applied credit when that credit is greater than zero, writes a `PAYMENT` ledger entry for the positive cash remainder when that remainder is greater than zero, sets the invoice's `amount_paid_cents` to its `total_cents`, and moves the invoice `ISSUED → PAID`. It then activates whatever the invoice was billing: a `Domain` goes `PENDING_PAYMENT → ACTIVE` with everything §3.2 describes, and a `HostingSubscription` goes `PROVISIONING → ACTIVE` with its first thirty-day billing period opened.

**Refunding.** A `BillingAdmin` refunds a `PAID` or `PARTIALLY_REFUNDED` invoice — any other status is `ERR_INVOICE_NOT_REFUNDABLE` — supplying an `amount_cents`, a `destination` of `CARD` or `CREDIT`, and a `reason`. The amount may not exceed what is still refundable, namely `amount_paid_cents` minus `amount_refunded_cents`; exceeding it is `ERR_REFUND_EXCEEDS_PAID`. A refund to `CARD` writes a `REFUND` ledger entry for the negative of the amount, restoring the account's `net_cash_cents`; a refund to `CREDIT` instead writes a `CREDIT_GRANT` entry for the positive amount, converting the money into store credit. Either way `amount_refunded_cents` grows by the refunded amount. A refund smaller than the outstanding refundable balance leaves the invoice `PARTIALLY_REFUNDED` — and further partial refunds keep it there — while a refund that exactly settles the outstanding refundable balance moves it to `REFUNDED`, which is terminal. Refunds move money only; they never undo the activations the payment performed. A domain paid for and then refunded stays registered.

### 3.9. Abuse Handling and the Suspension Cascade

Anyone at all, including an unauthenticated member of the public, may report a domain for abuse by naming the `domain_id`, a `category` of `PHISHING`, `MALWARE`, `SPAM` or `COPYRIGHT`, a `severity` of `LOW`, `HIGH` or `CRITICAL`, a `reporter_email`, and optionally an `evidence_url`. The report is created `OPEN`. Analysts, support staff and platform operators can read one or list them with filters on `domain_id` and `status`.

The workflow is a three-step fork with a segregation-of-duties gate in the middle. An `AbuseAnalyst` takes an `OPEN` report into review, moving it `OPEN → UNDER_REVIEW` and recording their own `X-User-ID` as the report's `reviewer_user_id`. A *different* `AbuseAnalyst` must then decide it, supplying a `decision_note`: the decision records that analyst's `X-User-ID` as `decider_user_id` and stamps `decided_at` from the logical clock. If the deciding analyst's `X-User-ID` equals the report's `reviewer_user_id`, the decision is refused with `ERR_SEGREGATION_OF_DUTIES`. A review attempted on a report that is not `OPEN`, or a decision attempted on a report that is not `UNDER_REVIEW`, is refused with `ERR_ABUSE_REPORT_INVALID_STATE`.

The two branches out of `UNDER_REVIEW` are deliberately lopsided. **Dismissal** — `UNDER_REVIEW → DISMISSED`, terminal — records `decider_user_id`, `decided_at` and the `decision_note`, and does nothing else at all: no domain changes, no account changes, no risk-score change. Its side-effect set is empty on purpose. **Upholding** — `UNDER_REVIEW → UPHELD`, also terminal — records the same three fields and then fires a five-level cascade.

Level two: the reported domain transitions `ACTIVE → SUSPENDED` with `suspension_reason` set to `ABUSE`. This is a *conditional* cascade — a domain that is not currently `ACTIVE` is simply left alone, and the report is still upheld. Level three, caused by that domain suspension: every `DnsRecord` of the domain has `serving_enabled` set to false; every `AddOn` of that domain whose `add_on_type` is `SSL_CERT` and whose `status` is `PENDING_VALIDATION` or `ACTIVE` transitions to `REVOKED` (a terminal state — the `validation_token` is retained for audit, but the certificate can never be revived); and every `AddOn` of that domain whose `add_on_type` is `EMAIL_MAILBOX` and whose `status` is `ACTIVE` transitions to `SUSPENDED`, keeping its storage reservation. Level four, caused by the same domain suspension: the owning account's `risk_score` is recomputed. Level five, caused by the new score: if the recomputed `risk_score` is 70 or above, the account transitions `ACTIVE → SUSPENDED`, which in turn suspends every `ACTIVE` or `OVER_QUOTA` hosting subscription of that account and forces `auto_renew_enabled` to false on every domain it owns.

**The risk score.** An account's `risk_score` is a decaying weighted sum over the `UPHELD` abuse reports against domains that account owns. Reports in `OPEN`, `UNDER_REVIEW` or `DISMISSED` contribute nothing. Each upheld report contributes its severity weight — 10 for `LOW`, 30 for `HIGH`, 60 for `CRITICAL` — halved once for every completed 90-day half-life that has elapsed since its `decided_at`. Concretely: the report's age in days is the elapsed time from `decided_at` to the logical clock now, taken in whole days (any partial day is discarded); that age is divided by 90 and the quotient rounded *down* to a whole number of half-lives; and the severity weight is multiplied by one half raised to that power. A `CRITICAL` report decided 89 days ago still contributes its full 60; the same report at 90 days contributes 30; at 180 days, 15. The contributions of all upheld reports are added together, the sum is rounded half up to a whole number, and the result is capped at 100 — so `risk_score` always lies between 0 and 100. The auto-suspension threshold is 70, reached at 70 and not merely above it: two upheld `HIGH` reports decided today total 60 and leave the account alone, while a `CRITICAL` plus a `LOW` decided today total 70 and suspend it.

The score is recomputed at exactly two moments: whenever an uphold suspends one of the account's domains, and on every expiry sweep, where the decay is refreshed so that an account's risk falls as its history ages. Nothing else moves it — in particular, a report sitting in `UNDER_REVIEW` never contributes to the number, even though it is already enough to block a transfer out.

Finally, only a `SupportAgent` can lift a domain suspension, by reinstating the individual domain with a `reason`. The domain must be `SUSPENDED` (anything else is `ERR_INVALID_DOMAIN_STATE`) and its account must already be back to `ACTIVE` — a domain belonging to a suspended account cannot be reinstated first. The reinstatement moves the domain `SUSPENDED → ACTIVE`, clears `suspension_reason` back to null, sets `serving_enabled` back to true on every record of the zone, and returns every `SUSPENDED` add-on of that domain to `ACTIVE`. Revoked certificates are *not* revived. The compensation is asymmetric by design: a suspended mailbox can be turned back on, but a revoked certificate is gone for good.

---

## 4. Endpoint Definitions

All endpoints are mounted under the `/registrar` prefix. Creating a new resource returns **201 Created**; modifying, transitioning, or reading an existing resource returns **200 OK**; a successful delete returns **204 No Content** with no body. Error responses use the status codes listed in §5, and the trigger conditions for each error are found in the narratives of §2 and §3, not in this table.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/registrar/accounts` | Open a registrar account. | Anonymous |
| GET | `/registrar/accounts/{id}` | Read an account, including its credit balance, net cash and risk score. | Registrant, SupportAgent, BillingAdmin, AbuseAnalyst, PlatformAdmin |
| POST | `/registrar/accounts/{id}/payment-method` | Attach a card token to the account. | Registrant, BillingAdmin |
| POST | `/registrar/accounts/{id}/credits` | Grant store credit; writes a CREDIT_GRANT ledger entry. | BillingAdmin |
| GET | `/registrar/accounts/{id}/ledger-entries` | List the account's money movements. | Registrant, BillingAdmin, PlatformAdmin |
| POST | `/registrar/accounts/{id}/reinstate` | Lift an abuse auto-suspension on the account. | SupportAgent |
| GET | `/registrar/domain-search` | Check availability and price of a name. | Anonymous, Registrant |
| POST | `/registrar/domains` | Register a domain; creates it PENDING_PAYMENT with an ISSUED invoice. | Registrant |
| GET | `/registrar/domains/{id}` | Read a domain; Anonymous callers get the WHOIS projection. | Anonymous, Registrant, SupportAgent, AbuseAnalyst, BillingAdmin, PlatformAdmin |
| GET | `/registrar/domains` | List domains. | Registrant, SupportAgent, AbuseAnalyst, BillingAdmin, PlatformAdmin |
| PATCH | `/registrar/domains/{id}/settings` | Toggle WHOIS privacy, auto-renew and the registrar transfer lock. | Registrant |
| GET | `/registrar/domains/{id}/renewal-quote` | Read-only renewal quote; nothing is persisted. | Registrant, BillingAdmin |
| POST | `/registrar/domains/{id}/renew` | Renew the domain and raise the renewal invoice. | Registrant, BillingAdmin |
| POST | `/registrar/domains/{id}/reinstate` | Lift an abuse suspension on a single domain. | SupportAgent |
| POST | `/registrar/domains/{id}/dns-records` | Create a DNS record in the domain's zone. | Registrant |
| GET | `/registrar/domains/{id}/dns-records` | List the zone's records. | Registrant, SupportAgent, PlatformAdmin |
| DELETE | `/registrar/dns-records/{id}` | Delete a DNS record. | Registrant |
| POST | `/registrar/transfer-requests` | Open an inbound or outbound transfer request. | Registrant |
| GET | `/registrar/transfer-requests/{id}` | Read a transfer request. | Registrant, SupportAgent, PlatformAdmin |
| GET | `/registrar/transfer-requests` | List transfer requests. | Registrant, SupportAgent, PlatformAdmin |
| POST | `/registrar/transfer-requests/{id}/submit` | Submit the request to the registry. | Registrant |
| POST | `/registrar/transfer-requests/{id}/registry-response` | Registry simulator: acknowledge or reject a pending transfer. | PlatformAdmin |
| POST | `/registrar/transfer-requests/{id}/retry` | Re-arm a rejected transfer request with a fresh EPP auth code. | Registrant |
| POST | `/registrar/hosting-plans` | Define a hosting plan. | BillingAdmin |
| POST | `/registrar/hosting-subscriptions` | Buy a hosting plan; creates the subscription and its invoice. | Registrant |
| GET | `/registrar/hosting-subscriptions/{id}` | Read a subscription. | Registrant, SupportAgent, BillingAdmin, PlatformAdmin |
| GET | `/registrar/hosting-subscriptions` | List subscriptions. | Registrant, SupportAgent, BillingAdmin, PlatformAdmin |
| POST | `/registrar/hosting-subscriptions/{id}/usage-records` | Ingest a bandwidth usage record. | PlatformAdmin |
| GET | `/registrar/hosting-subscriptions/{id}/usage-records` | List usage records. | Registrant, BillingAdmin, PlatformAdmin |
| POST | `/registrar/hosting-subscriptions/{id}/billing-periods` | Open an additional metering period. | BillingAdmin |
| GET | `/registrar/hosting-subscriptions/{id}/billing-periods` | List the subscription's metering periods. | Registrant, BillingAdmin, PlatformAdmin |
| POST | `/registrar/billing-periods/{id}/close` | Close a period, bill the final overage and reset the counter. | BillingAdmin |
| POST | `/registrar/add-ons` | Buy an SSL certificate or an email mailbox. | Registrant |
| GET | `/registrar/add-ons/{id}` | Read an add-on. | Registrant, SupportAgent, BillingAdmin, PlatformAdmin |
| GET | `/registrar/add-ons` | List add-ons. | Registrant, SupportAgent, BillingAdmin, PlatformAdmin |
| POST | `/registrar/add-ons/{id}/validate` | DNS-01 validation of an SSL certificate. | Registrant |
| DELETE | `/registrar/add-ons/{id}` | Cancel an add-on. | Registrant |
| GET | `/registrar/invoices/{id}` | Read an invoice with its computed money fields. | Registrant, BillingAdmin, PlatformAdmin |
| GET | `/registrar/invoices` | List invoices. | Registrant, BillingAdmin, PlatformAdmin |
| GET | `/registrar/invoices/{id}/line-items` | List the invoice's line items. | Registrant, BillingAdmin, PlatformAdmin |
| POST | `/registrar/invoices/{id}/apply-promo` | Apply or replace a promo code on an issued invoice. | Registrant, BillingAdmin |
| POST | `/registrar/invoices/{id}/pay` | Pay an issued invoice; activates the billed subject. | Registrant, BillingAdmin |
| POST | `/registrar/invoices/{id}/refund` | Refund a paid invoice to the card or to store credit. | BillingAdmin |
| POST | `/registrar/promo-codes` | Create a promo code. | BillingAdmin |
| POST | `/registrar/abuse-reports` | Report a domain for abuse. | Anonymous |
| GET | `/registrar/abuse-reports/{id}` | Read an abuse report. | AbuseAnalyst, SupportAgent, PlatformAdmin |
| GET | `/registrar/abuse-reports` | List abuse reports. | AbuseAnalyst, SupportAgent, PlatformAdmin |
| POST | `/registrar/abuse-reports/{id}/review` | Take a report into review. | AbuseAnalyst |
| POST | `/registrar/abuse-reports/{id}/uphold` | Uphold a report and fire the suspension cascade. | AbuseAnalyst |
| POST | `/registrar/abuse-reports/{id}/dismiss` | Dismiss a report. | AbuseAnalyst |
| POST | `/registrar/_clock/set_current_utc` | Set the server's logical clock. | PlatformAdmin |
| POST | `/registrar/_ops/run-expiry-sweep` | Advance the expiry ladder, auto-renew, expire add-ons and refresh risk decay. | PlatformAdmin |

---

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_ACCOUNT_SUSPENDED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_DOMAIN_NOT_FOUND` | 404 |
| `ERR_DNS_RECORD_NOT_FOUND` | 404 |
| `ERR_HOSTING_PLAN_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_ADDON_NOT_FOUND` | 404 |
| `ERR_TRANSFER_REQUEST_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_BILLING_PERIOD_NOT_FOUND` | 404 |
| `ERR_ABUSE_REPORT_NOT_FOUND` | 404 |
| `ERR_PROMO_CODE_NOT_FOUND` | 404 |
| `ERR_STALE_DOMAIN_VERSION` | 412 |
| `ERR_STALE_INVOICE_VERSION` | 412 |
| `ERR_DOMAIN_NOT_RENEWABLE` | 409 |
| `ERR_INVALID_DOMAIN_STATE` | 409 |
| `ERR_ADDON_NOT_PENDING_VALIDATION` | 409 |
| `ERR_TRANSFER_INVALID_STATE` | 409 |
| `ERR_INVOICE_NOT_PAYABLE` | 409 |
| `ERR_INVOICE_NOT_REFUNDABLE` | 409 |
| `ERR_PERIOD_ALREADY_CLOSED` | 409 |
| `ERR_ABUSE_REPORT_INVALID_STATE` | 409 |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_ABUSE_HOLD_ACTIVE` | 409 |
| `ERR_DNS_RECORD_IN_USE` | 409 |
| `ERR_DNS_VALIDATION_FAILED` | 409 |
| `ERR_DOMAIN_LOCKED` | 409 |
| `ERR_TRANSFER_LOCK_PERIOD` | 409 |
| `ERR_EPP_AUTH_MISMATCH` | 409 |
| `ERR_TRANSFER_MAX_ATTEMPTS` | 409 |
| `ERR_DOMAIN_UNAVAILABLE` | 409 |
| `ERR_MAILBOX_ADDRESS_TAKEN` | 409 |
| `ERR_SSL_INTERVAL_CONFLICT` | 409 |
| `ERR_BILLING_PERIOD_OVERLAP` | 409 |
| `ERR_MAX_TERM_EXCEEDED` | 422 |
| `ERR_USAGE_OUTSIDE_PERIOD` | 422 |
| `ERR_PROMO_NOT_APPLICABLE` | 422 |
| `ERR_PROMO_MIN_NOT_MET` | 422 |
| `ERR_STORAGE_QUOTA_EXCEEDED` | 422 |
| `ERR_PAYMENT_METHOD_REQUIRED` | 402 |
| `ERR_REFUND_EXCEEDS_PAID` | 422 |
