# Greeting-Card Reminder API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Greeting-Card & Occasion-Reminder Service, a platform that lets people never miss a birthday, anniversary, or holiday again. An account holder builds an address book of recipients, attaches recurring occasion reminders to each of them, and dispatches personalized, hand-written greeting cards — optionally paired with a small gift enclosure — through a studio fulfillment pipeline that runs from personalization and proofing all the way to postal tracking and delivery.

The service is organized around two ideas that operate in parallel. First, a **card send** progresses through a physical fulfillment pipeline: it is drafted, proofed and approved by the sender, scheduled, produced by a reserved handwriting artist, mailed, and finally delivered. Second, every send is backed by a **card-credit economy**: subscriptions grant credits on a monthly cycle, each submitted send holds one credit, production settles it, and a cancellation refunds it. Because the platform must also fire recurring birthday reminders on its own, all time-sensitive behavior is driven by a logical clock and an explicit scheduler tick rather than wall-clock time, which makes the system fully deterministic and testable. The remainder of this document defines the global contracts that every endpoint honors, the business rules that govern each workflow, and the complete endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they are acting. A request that omits either header, or supplies a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation — or an account holder attempts to act on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly three roles: `AccountHolder`, `StudioOperator`, and `PlatformAdmin`. An `AccountHolder` is the customer; they own their account, contacts, reminders, and orders, and they alone review and approve proofs. A `StudioOperator` is studio staff who manage the catalog, verify mailing addresses, reserve artists, revise proofs, drive production and mailing, and advance tracking. A `PlatformAdmin` is the system operator who provisions accounts, posts credit adjustments, and drives the logical clock and the scheduler.

The `AccountHolder` role is entity-backed by the `Account` entity: when `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `Account`, and ownership checks on any resource that references an account compare that resource's `account_id` to `X-User-ID`. A contact, important date, order, or subscription is owned by the account it belongs to (directly through `account_id`, or transitively through the contact it hangs from), and an account holder acting on a resource whose owning account is not their own `X-User-ID` is rejected with `ERR_UNAUTHORIZED`. By contrast, both `StudioOperator` and `PlatformAdmin` carry an opaque identity: for these two roles `X-User-ID` is an operator identifier not tied to any persisted entity. The server accepts it for authentication but does not compare it against any entity's `id` for ownership.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100 — a value outside that range is silently clamped into it (below 1 becomes 1, above 100 becomes 100) rather than rejected, while a non-integer value is rejected with `ERR_VALIDATION`. The `offset` parameter is the number of items to skip and defaults to 0; a negative offset is clamped to 0 and a non-integer offset is rejected with `ERR_VALIDATION`. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. The one deliberate exception is the account's credit ledger, which is returned newest first. Every list response echoes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope. The account-subscription listing (`GET /accounts/{id}/subscription`), the order-proofs listing (`GET /orders/{id}/proofs`), and the order-shipment listing (`GET /orders/{id}/shipment`) are the exceptions: they return their full array unpaginated and omit these four pagination fields from `meta`.

### 2.4. Common Resource Properties and Versioning

Most resources are full first-class entities and carry a standard set of system-managed fields: an `id` formatted as a UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; an `updated_at` timestamp, in the same format, refreshed on every mutation; and a `version` integer that starts at 1 on creation and increments by one on each mutation. This set applies to `Account`, `Subscription`, `Contact`, `ImportantDate`, `Card`, `GiftItem`, `HandwritingArtist`, `Order`, `Proof`, `ArtistAssignment`, and `Shipment`.

The single exception is the `CreditTransaction`, which is an append-only ledger row: it carries only `id` and `created_at`. It has neither `updated_at` nor `version`, because a ledger row is never modified once written. When a computed field such as an account's balance or an artist's reservation count is recomputed as a side effect of an operation, that recomputation is itself a mutation of the owning resource — it refreshes `updated_at` and increments `version`.

### 2.5. The Logical Clock and the Scheduler

All temporal behavior in the system is governed by a **logical clock**, never by wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and it holds that value until a `PlatformAdmin` explicitly sets it; before any set call it never falls back to real time. An admin advances the clock by supplying a target instant via the `to_iso8601` field, and the response reports the new value as `current_utc`. Every temporal check in this document — send-date validation, production timing, reminder triggers, subscription period boundaries, and the `mailed_at` / `delivered_at` stamps — reads this clock.

A companion **scheduler tick** is likewise driven explicitly by a `PlatformAdmin`. Each tick performs two sweeps and reports what it did through `fired_important_date_ids`, `created_order_ids`, and `renewed_subscription_ids`. The behavior of these two sweeps is detailed in the recurring-sends and renewal narratives of Section 3.

### 2.6. The Card-Credit Ledger

Card credits are the currency of the platform, tracked as an append-only ledger. Each `CreditTransaction` records the owning `account_id`, a signed `delta`, a `reason` that is one of `SUBSCRIPTION_GRANT`, `PRORATION_GRANT`, `ORDER_HOLD`, `ORDER_REFUND`, or `MANUAL_ADJUST`, and a `balance_after` snapshot. An account's `card_credit_balance` is a computed quantity equal to the sum of the `delta` of every credit transaction belonging to that account, with no status filter; it is recomputed on every ledger insert as that raw signed sum and is not clamped, so a `MANUAL_ADJUST` debit that exceeds the current balance drives it below zero. When the balance is recomputed, transactions are considered in `created_at` ascending order so that each row's `balance_after` reflects the running total immediately after that row was applied. Credits are a conserved quantity: an `ORDER_HOLD` of minus one paired with a later `ORDER_REFUND` of plus one leaves the account's balance exactly where it started.

### 2.7. Monetary Precision and Rounding

All monetary amounts in the system are integer cents; no field ever carries fractional cents. Weights are integer grams and credits are integer counts. Two calculations perform rounding — the gift-line discount and the sales tax — and both use the **round-half-up** method to a whole number of cents. The rounding order is pinned and is a correctness requirement: the discount is computed on the *summed* gift line and rounded once, and the tax is then computed on the *summed, discounted* line and rounded once. Rounding each unit individually and then summing is explicitly forbidden, because it can yield a different number of cents. Proration of credits on a mid-cycle tier change likewise produces whole credits, using a ceiling as described in Section 3.

### 2.8. Optimistic Concurrency Control

Submitting a card send holds one card credit against the sender's account, and that hold depends on the account's credit balance as the caller last observed it. To prevent a caller from acting on a stale view of that balance, the submit operation requires the caller to pass `expected_account_version` carrying the `version` of the `Account` they last read. If the account's current `version` has advanced since then — because another submit already held a credit, or because a credit adjustment or a subscription grant posted to the ledger — the caller's view is stale and the submit is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). Two submits that would each individually succeed (the account holds enough credits for either one alone) are thereby serialized: the first advances the account's version, and the second, still presenting the old version, is turned away rather than silently overwriting a balance it never saw. This is the only operation that takes a version field; no other endpoint requires or accepts one.

### 2.9. Validation Ordering and Nested-Resource Resolution

When an endpoint could fail several checks at once, the system evaluates them in a fixed precedence so that the returned error is deterministic. A syntactically malformed body, a missing required field, or an invalid enum or type value is a bad request and yields `ERR_VALIDATION`. Authentication comes first among the semantic checks: a missing or malformed header yields `ERR_UNAUTHENTICATED` before anything else. Authorization is next, yielding `ERR_UNAUTHORIZED` for a forbidden role or an ownership violation. Existence checks follow: every resource named by a path segment or a foreign-key body field must resolve, and path identifiers are validated left to right so that the first unresolved identifier in the path determines which not-found error is returned — `ERR_ACCOUNT_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_IMPORTANT_DATE_NOT_FOUND`, `ERR_CARD_NOT_FOUND`, `ERR_GIFT_ITEM_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, or `ERR_SHIPMENT_NOT_FOUND`, according to which resource failed to resolve. Only after existence is confirmed does the system check whether the target resource is in a state that permits the requested transition; an illegal transition yields `ERR_INVALID_STATE`, and this state check takes precedence over every business rule that follows it. After state, the domain-specific business checks (catalog availability, address verification, proof approval, artist assignment, temporal windows, capacity, quantity, credit sufficiency, and finally optimistic concurrency) are evaluated in that order, as detailed alongside the workflows in Section 3.

### 2.10. Parallel Order Dimensions and Cascades

An order evolves along two independent dimensions at once. Its `status` follows the fulfillment pipeline — `DRAFT`, `PENDING_PROOF`, `PROOF_APPROVED`, `SCHEDULED`, `IN_PRODUCTION`, `MAILED`, `DELIVERED`, and the terminal `CANCELLED` — while its `credit_status` follows the accounting lifecycle — `NONE`, `HELD`, `SETTLED`, and the terminal `REFUNDED`. These two dimensions advance on their own triggers, and much of the business logic is precisely about keeping them consistent as an operation touches both at the same time. Several operations also cascade across entities: approving a proof advances the owning order, producing an order completes its artist reservation, delivering a shipment delivers its order, and cancelling an order can simultaneously refund a credit, release an artist, and void a proof. Every such cascade independently mutates each affected resource, refreshing its `updated_at` and incrementing its `version`.

## 3. Business Logic & Workflows

### 3.1. Accounts, Subscriptions, and the Credit Economy

A `PlatformAdmin` provisions a new account from an `email` and a `display_name`. A freshly created account is `ACTIVE` (accounts are otherwise `SUSPENDED`), begins with a `card_credit_balance` of zero, and takes `version` 1. Anyone provisioning or reading an account sees the live computed balance and current version.

An account funds itself through a subscription. Creating a subscription selects a `tier`, which is one of `FREE`, `PLUS`, or `PRO`, and the tier alone determines three derived fields: the `monthly_card_credits` granted each cycle (0 for `FREE`, 4 for `PLUS`, 12 for `PRO`), the `monthly_fee_cents` (0, 1200, and 3000 respectively), and the gift-line `discount_pct` (0.0, 0.10, and 0.20 respectively). An account may hold only one `ACTIVE` subscription at a time; this is not enforced on creation, so a second `create` still succeeds and simply adds another `ACTIVE` subscription. On creation the subscription is stamped `ACTIVE`; its `current_period_start` is set to the current logical-clock instant, its `current_period_end` is set to thirty days after that start, and its `next_renewal_at` is set equal to the period end. Creating the subscription grants the tier's full monthly credits immediately: a `CreditTransaction` with reason `SUBSCRIPTION_GRANT` and a positive `delta` equal to the tier's monthly credits is written, the account's balance is recomputed, and the account's `version` is incremented by one.

When an account holder changes tier mid-cycle, the subscription stays `ACTIVE` and a **prorated** grant is issued rather than a full one. The system first determines the whole number of days remaining in the current period by taking the difference between `current_period_end` and the current logical clock and rounding *up* to whole days, never below zero. The prorated grant is then the new tier's monthly credit count multiplied by that days-remaining figure, divided by the thirty-day period length, with the result rounded *up* to a whole number of credits. This grant is recorded as a `CreditTransaction` with reason `PRORATION_GRANT`, the balance is recomputed, and the account's `version` is incremented by one; whenever fewer than thirty days remain, the prorated grant is strictly smaller than the full grant. Cancelling a subscription moves it from `ACTIVE` to `CANCELLED` and performs no clawback — any credits already granted are retained. A `PlatformAdmin` may additionally post a direct credit adjustment against an account, supplying a signed `delta` and a `reason` (defaulting to `MANUAL_ADJUST`); this writes a ledger row, recomputes the balance, increments the account's `version`, and returns that newly created `CreditTransaction` (with `201`). The account's full ledger can be listed newest-first, and its lone subscription can be read back through the account.

### 3.2. Building the Address Book and Occasion Reminders

An account holder assembles an address book of `Contact` records. A contact is created against an owning `account_id` and carries a `full_name` and a mailing address: `address_line1`, an optional `address_line2`, `city`, `region`, `postal_code`, and `country_code`. The `region` is a state or region code such as CA, and it later drives the sales-tax rate applied to any gift line. A new contact begins `UNVERIFIED`. Addresses can also be loaded in bulk by supplying a `source` label and an array of `rows`; each well-formed row becomes one `UNVERIFIED` contact, rows missing required address fields are skipped, and the response reports `imported_count`, `skipped_count`, and the created `contact_ids`. A bulk import whose `rows` array is empty is rejected with `ERR_EMPTY_IMPORT`.

Before a card can be sent to a contact, a `StudioOperator` verifies the address. Verification supplies a `result`, driving `address_status` from `UNVERIFIED` to `VERIFIED`, from `UNVERIFIED` to `UNDELIVERABLE`, or from `VERIFIED` to `UNDELIVERABLE`. Contacts can be listed under their account and optionally filtered by `address_status`.

Against each contact, the account holder attaches occasion reminders. An `ImportantDate` records the owning `contact_id`, an `occasion_type` of `BIRTHDAY`, `ANNIVERSARY`, `HOLIDAY`, or `CUSTOM`, the `event_date` itself, and a `lead_days` count (a whole number of zero or more) expressing how many days before the event a send should fire. A reminder's `next_trigger_at` is computed as the event date minus that lead-days offset, expressed in ISO 8601 UTC with three fractional digits. A reminder also carries a `recurrence` of either `NONE` (the default) or `ANNUAL`; on each annual firing the underlying event advances by one year, so the next trigger becomes that year-advanced event date minus the same lead-days offset. A reminder further carries an `auto_send` flag (default false) and a `default_card_id`; when `auto_send` is true the `default_card_id` must be supplied, and a request that turns on auto-send without one is rejected with `ERR_AUTO_SEND_CARD_REQUIRED`. Newly created reminders are `ACTIVE`; an account holder may archive one, moving its `status` from `ACTIVE` to `ARCHIVED`, after which it no longer fires.

Reminders of the same kind on the same person must not crowd each other. When a new occasion is added, the system considers its reminder window — the closed interval running from the event date minus the lead days through the event date itself — and requires it to sit at least two days clear of the reminder window of every existing `ACTIVE` important date of the same `occasion_type` on the same contact. Windows that touch, overlap, or fall within that two-day buffer conflict, and the create is rejected with `ERR_REMINDER_WINDOW_OVERLAP`. Reminders can be fetched individually or listed with optional filters on `contact_id`, `default_card_id`, and `status`.

### 3.3. The Catalog: Cards, Gifts, and Handwriting Artists

Studio staff and platform admins maintain the sendable catalog. A `Card` is created with a `sku`, a `title`, a `category` (one of `BIRTHDAY`, `THANK_YOU`, `HOLIDAY`, `SYMPATHY`, or `CUSTOM`), a `base_price_cents` price of zero or more that is covered by a single card credit at send time, and a `weight_grams` weight of zero or more that feeds postage selection. A `GiftItem` enclosure is created with a `sku`, a `title`, a `kind` (one of `GIFT_CARD`, `FLOWERS`, `CHOCOLATE`, or `CUSTOM_NOTE`), a per-unit `price_cents` of zero or more (which is taxable and eligible for the subscription discount), and a per-unit `weight_grams` of zero or more (which also contributes to postage). Both cards and gift items begin `ACTIVE` and can be retired, moving `status` from `ACTIVE` to `RETIRED`; retired catalog entries may no longer be ordered.

A `HandwritingArtist` is created with a `name`, a studio `region_code`, and a `daily_capacity` of at least one, which caps how many reserved windows the artist may hold on any single calendar date. An artist starts `AVAILABLE` (as opposed to `OFF`) and exposes a computed `reserved_assignment_count` that tracks how many of the artist's assignments are currently `RESERVED`; this count is recomputed whenever an assignment is created, released, or completed.

### 3.4. Placing and Submitting a Card Send

An account holder opens a send as a `DRAFT` `Order`. Creation names the sender's `account_id`, the recipient `contact_id`, and the `card_id` to send, and supplies the handwritten `message_text` and the requested `scheduled_send_at` mail-out instant. Three optional inputs shape the send further: a `font_style` of `SCRIPT` (the default), `PRINT`, or `CASUAL`; a `gift_item_id` enclosure together with a `gift_quantity`; and an `important_date_id`, which is normally populated only when the scheduler itself creates the order from a recurring occasion, though a client-supplied value is accepted as-is on manual create and is not validated for existence. At create time the card must be `ACTIVE`, or the request is rejected with `ERR_CARD_RETIRED`; if a gift item is named it too must be `ACTIVE`, or the request is rejected with `ERR_GIFT_ITEM_RETIRED`; and whenever a `gift_item_id` is present the `gift_quantity` must be at least one, failing with `ERR_GIFT_QUANTITY_INVALID` (a bare draft with no gift carries a quantity of zero).

A new draft has `status` `DRAFT` and `credit_status` `NONE`, and the system computes a provisional `estimated_total_cents` and the chosen `postage_cents`. Postage is selected by total weight, where the total weight is the card's weight plus, when a gift is enclosed, the gift's per-unit weight multiplied by the gift quantity. The postage tier is the first tier whose weight ceiling the total weight does not exceed: 150 cents for a total of at most 30 grams, 250 cents for at most 60 grams, 450 cents for at most 120 grams, and 800 cents for anything heavier. The estimated total is this postage plus the gift line — the gift's per-unit price multiplied by the gift quantity, or zero when no gift is enclosed. At this estimate stage no subscription discount and no tax are applied, so `gift_discount_cents` and `tax_cents` remain zero and `final_total_cents` remains null; those are computed only at production.

Submitting a draft is the account holder's commitment, and it advances the order from `DRAFT` to `PENDING_PROOF` while moving its credit dimension from `NONE` to `HELD`. Submission is guarded by a precise sequence of checks: the order must actually be in `DRAFT`; the card must still be `ACTIVE` (`ERR_CARD_RETIRED`); the recipient contact's address must be `VERIFIED`, or the submit fails with `ERR_ADDRESS_NOT_VERIFIED`; the requested `scheduled_send_at` must lie strictly in the future relative to the current logical clock, or it fails with `ERR_SEND_DATE_IN_PAST`; the account must hold at least one credit, or it fails with `ERR_INSUFFICIENT_CREDITS`; and finally the supplied `expected_account_version` must match the account's current `version`, or it fails with `ERR_STALE_ACCOUNT_VERSION`. When all of these pass, the system holds a credit by writing a `CreditTransaction` with reason `ORDER_HOLD` and a `delta` of minus one, recomputes the account's balance, increments the account's `version` by one, and creates a fresh `Proof` in `PENDING` status with a `revision_count` of zero for the order.

### 3.5. The Proof Review Loop

Every submitted order carries exactly one live `Proof`, which references its `order_id` and holds a `proof_image_ref` pointing at the rendered image plus a `revision_count` and optional `reviewer_notes`. The proof drives the sender's review cycle. From `PENDING`, the account holder may approve it, moving the proof from `PENDING` to `APPROVED`; this cascade advances the owning order from `PENDING_PROOF` to `PROOF_APPROVED`. Alternatively, the account holder may request changes, moving the proof from `PENDING` to `CHANGES_REQUESTED`; this stores the supplied `reviewer_notes` and increments `revision_count` by one. A `StudioOperator` then revises the proof, moving it back from `CHANGES_REQUESTED` to `PENDING` and refreshing the `proof_image_ref`. This request-changes/revise cycle may repeat any number of rounds before the proof is finally approved. A proof may also be voided as a consequence of its order being cancelled, moving from `PENDING` or `CHANGES_REQUESTED` to the terminal `VOIDED`. Proofs for an order can be listed back through the order.

### 3.6. Scheduling, Artist Reservation, and Production

Once a proof is approved, the send is confirmed onto the calendar. Confirming the schedule advances the order from `PROOF_APPROVED` to `SCHEDULED`; it requires that the proof indeed be `APPROVED`, that the recipient's address still be `VERIFIED` (otherwise `ERR_ADDRESS_NOT_VERIFIED`), and that the `scheduled_send_at` still lie strictly in the future relative to the logical clock (otherwise `ERR_SEND_DATE_IN_PAST`).

A card is produced by a reserved handwriting artist. A `StudioOperator` reserves an artist for an order by supplying an `artist_id` and a half-open production window running from `window_start` up to but not including `window_end`. Reserving creates an `ArtistAssignment` in `RESERVED` status, records the chosen artist on the order's `artist_id`, and recomputes the artist's `reserved_assignment_count`. Two constraints guard the reservation. First, the requested window must not overlap any existing `RESERVED` window for the same artist; because the intervals are half-open, two windows that merely touch at an endpoint do not conflict, but any true overlap is rejected with `ERR_ARTIST_WINDOW_CONFLICT`. Second, adding the reservation must not push the artist's number of `RESERVED` assignments whose window starts on the same calendar date as this window's start above the artist's `daily_capacity`; exceeding it is rejected with `ERR_ARTIST_CAPACITY_EXCEEDED`. Assignments can be fetched directly or listed by `artist_id`, `order_id`, and/or `status`; because the catalogue defines no dedicated assignment-not-found error, a direct fetch by an id that does not resolve returns `ERR_ORDER_NOT_FOUND`.

Producing the order advances it from `SCHEDULED` to `IN_PRODUCTION` and is the moment money and credits settle. Production requires that the order be `SCHEDULED`, that a `RESERVED` `ArtistAssignment` exist for it (otherwise `ERR_ARTIST_NOT_ASSIGNED`), that the order's proof be `APPROVED` (otherwise `ERR_PROOF_NOT_APPROVED`), and that the logical clock have reached or passed the `scheduled_send_at` instant — producing before that instant is rejected with `ERR_TOO_EARLY_TO_PRODUCE`. When it proceeds, production computes the final monetary figures, settles the credit by moving `credit_status` from `HELD` to `SETTLED`, and completes the artist reservation by moving the `ArtistAssignment` from `RESERVED` to `COMPLETED` and recomputing the artist's `reserved_assignment_count`.

The final money is computed as follows. Postage is recomputed from the same weights as at estimate time, using the same tier ladder. The gift line is the gift's per-unit `price_cents` multiplied by `gift_quantity`, summed once. The discount fraction is the account's `ACTIVE` subscription `discount_pct` (the most recently created one, when several are `ACTIVE`), or zero when there is no active subscription; the `gift_discount_cents` is that fraction applied to the summed gift line and rounded half-up to whole cents in a single rounding step. The taxable base is the gift line minus that discount — postage and the credit-covered card itself are never taxed. The tax rate is chosen from the recipient contact's `region`: 0.0725 for CA, 0.08875 for NY, 0.0625 for TX, 0.065 for WA, and 0.0 for any other region. The `tax_cents` is that rate applied to the taxable base and rounded half-up to whole cents in a single rounding step. The `final_total_cents` is then the postage plus the discounted gift line plus the tax — that is, postage plus the quantity gift price reduced by the discount, plus the tax.

### 3.7. Mailing, Tracking, and Delivery

After production, a `StudioOperator` mails the order, advancing it from `IN_PRODUCTION` to `MAILED`; mailing requires the proof to be `APPROVED`. Mailing creates a `Shipment` for the order in `LABEL_CREATED` status with the requested `carrier` (either `USPS`, the default, or `UPS`) and a server-minted `tracking_number`, and stamps both the order's `mailed_at` and the shipment's `mailed_at` with the current logical-clock instant. The shipment then progresses as the operator advances its tracking via a supplied `to_status`: from `LABEL_CREATED` to `IN_TRANSIT`, from `IN_TRANSIT` to `DELIVERED`, or from `IN_TRANSIT` to `RETURNED`. When a shipment reaches `DELIVERED`, the change cascades to the order, advancing it from `MAILED` to the terminal `DELIVERED` and stamping the order's `delivered_at` and the shipment's `delivered_at` with the current logical clock. An order's shipment can be read back through the order.

### 3.8. Cancellation, Refunds, and Reversal Cascades

An order may be cancelled from any pre-delivery pipeline state, always ending in the terminal `CANCELLED`, but the accounting and cascade consequences depend on where in the pipeline it was. Cancelling a `DRAFT` order moves nothing else, because no credit was ever held. Cancelling from `PENDING_PROOF`, `PROOF_APPROVED`, or `SCHEDULED` — states in which `credit_status` is `HELD` — refunds the held credit by moving `credit_status` from `HELD` to `REFUNDED`, writing a `CreditTransaction` with reason `ORDER_REFUND` and a `delta` of plus one, recomputing the account balance, and incrementing the account's `version` by one. Cancelling from `IN_PRODUCTION`, where the credit is `SETTLED`, likewise refunds it by moving `credit_status` from `SETTLED` to `REFUNDED`, with the same plus-one `ORDER_REFUND` ledger row, balance recompute, and account `version` bump.

Cancellation also unwinds the physical commitments. If the order still holds a `RESERVED` artist assignment, that assignment is released — moved from `RESERVED` to `RELEASED` — and the artist's `reserved_assignment_count` is recomputed. If the order's proof is still open in `PENDING` or `CHANGES_REQUESTED`, it is voided to `VOIDED`. In short, a single cancellation can simultaneously refund a credit, release an artist, and void a proof, each as its own tracked mutation.

### 3.9. Recurring Sends and Subscription Renewals

The scheduler tick is where recurring reminders and subscription cycles come to life. On each tick, the system first sweeps due reminders: for every `ACTIVE` `ImportantDate` whose `auto_send` is true and whose `next_trigger_at` is at or before the current logical clock, and whose contact's address is verified and whose account holds at least one credit, the scheduler auto-creates an order for the reminder's `default_card_id` — carrying an empty `message_text`, the default `SCRIPT` font, and no gift — with the send instant taken from the occasion's event date, and immediately auto-submits it so that one credit is held. The reminder's underlying event date and `next_trigger_at` are then advanced by one year — that is, `next_trigger_at` becomes the year-advanced event date minus the same lead-days offset — regardless of whether the reminder's `recurrence` is `NONE` or `ANNUAL`, so the occasion does not re-fire until the following cycle. The tick reports each fired reminder and each created order.

The tick then sweeps subscriptions: for every `ACTIVE` `Subscription` whose `next_renewal_at` is at or before the current logical clock, the scheduler grants the tier's full `monthly_card_credits` as a `CreditTransaction` with reason `SUBSCRIPTION_GRANT`, recomputes the balance, increments the account's `version` by one, and advances the subscription's `current_period_start`, `current_period_end`, and `next_renewal_at` forward by the thirty-day period length. Renewed subscriptions are reported back in the tick's summary. Orders themselves can be listed and filtered by any of their foreign keys or by pipeline status — `account_id`, `contact_id`, `card_id`, `gift_item_id`, `artist_id`, `important_date_id`, or `status`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`; operations that read a resource or drive an existing resource through a transition return `200 OK`. The following table lists the HTTP contract only; request and response details are reconstructed from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Create an account (balance starts at 0) | PlatformAdmin |
| GET | `/accounts/{id}` | Fetch one account with computed balance and version | PlatformAdmin, AccountHolder |
| POST | `/accounts/{id}/subscriptions` | Create the account's subscription; grants full monthly credits | PlatformAdmin, AccountHolder |
| GET | `/accounts/{id}/subscription` | List the account's subscription(s) | PlatformAdmin, AccountHolder |
| POST | `/subscriptions/{id}/change-tier` | Change tier mid-cycle; grants prorated credits | PlatformAdmin, AccountHolder |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription (no clawback) | PlatformAdmin, AccountHolder |
| POST | `/accounts/{id}/credit-adjustments` | Admin credit adjustment (grant or debit) | PlatformAdmin |
| GET | `/accounts/{id}/credit-transactions` | List the account's credit ledger (newest first) | PlatformAdmin, AccountHolder |
| POST | `/contacts` | Create a contact (address UNVERIFIED) | AccountHolder, PlatformAdmin |
| GET | `/accounts/{id}/contacts` | List the account's contacts | AccountHolder, PlatformAdmin |
| GET | `/contacts/{id}` | Fetch one contact | AccountHolder, StudioOperator, PlatformAdmin |
| POST | `/accounts/{id}/contacts/bulk-import` | Bulk address-book import | AccountHolder, PlatformAdmin |
| POST | `/contacts/{id}/verify-address` | Mark address VERIFIED or UNDELIVERABLE | StudioOperator, PlatformAdmin |
| POST | `/contacts/{id}/important-dates` | Create an occasion reminder for a contact | AccountHolder, PlatformAdmin |
| GET | `/important-dates/{id}` | Fetch one important date | AccountHolder, PlatformAdmin |
| GET | `/important-dates` | Filter important dates by contact and/or default card | AccountHolder, PlatformAdmin |
| POST | `/important-dates/{id}/archive` | Archive a reminder so it stops firing | AccountHolder, PlatformAdmin |
| POST | `/cards` | Create a catalog card | PlatformAdmin, StudioOperator |
| GET | `/cards/{id}` | Fetch one catalog card | AccountHolder, StudioOperator, PlatformAdmin |
| POST | `/cards/{id}/retire` | Retire a catalog card | PlatformAdmin, StudioOperator |
| POST | `/gift-items` | Create a catalog gift/enclosure item | PlatformAdmin, StudioOperator |
| POST | `/gift-items/{id}/retire` | Retire a gift item | PlatformAdmin, StudioOperator |
| POST | `/artists` | Create a handwriting artist | PlatformAdmin, StudioOperator |
| GET | `/artists/{id}` | Fetch one artist with computed reservation count | StudioOperator, PlatformAdmin |
| POST | `/orders` | Create a DRAFT card send; computes the estimate | AccountHolder, PlatformAdmin |
| GET | `/orders/{id}` | Fetch one order | AccountHolder, StudioOperator, PlatformAdmin |
| GET | `/orders` | Filter orders by any foreign key or status | AccountHolder, StudioOperator, PlatformAdmin |
| POST | `/orders/{id}/submit` | Submit a DRAFT order; holds a credit under OCC | AccountHolder |
| POST | `/orders/{id}/assign-artist` | Reserve an artist into a production window | StudioOperator |
| GET | `/artist-assignments/{id}` | Fetch one artist assignment | StudioOperator, PlatformAdmin |
| GET | `/artist-assignments` | Filter assignments by artist and/or order | StudioOperator, PlatformAdmin |
| GET | `/orders/{id}/proofs` | List proofs for an order | AccountHolder, StudioOperator |
| POST | `/proofs/{id}/approve` | Approve a proof; cascades the order | AccountHolder |
| POST | `/proofs/{id}/request-changes` | Request changes on a proof | AccountHolder |
| POST | `/proofs/{id}/revise` | Studio uploads a revised proof | StudioOperator |
| POST | `/orders/{id}/schedule` | Confirm the send schedule | StudioOperator, AccountHolder |
| POST | `/orders/{id}/produce` | Start production; settles the credit | StudioOperator |
| POST | `/orders/{id}/mail` | Mail the produced order; creates the shipment | StudioOperator |
| GET | `/orders/{id}/shipment` | List the order's shipment | AccountHolder, StudioOperator |
| POST | `/shipments/{id}/advance` | Advance tracking; DELIVERED cascades the order | StudioOperator |
| POST | `/orders/{id}/cancel` | Cancel an order; refunds, releases, voids | AccountHolder, StudioOperator |
| POST | `/_clock/set_current_utc` | Set the test-driving logical clock | PlatformAdmin |
| POST | `/_scheduler/run` | Fire due reminders and renew due subscriptions | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_CONTACT_NOT_FOUND` | 404 |
| `ERR_IMPORTANT_DATE_NOT_FOUND` | 404 |
| `ERR_CARD_NOT_FOUND` | 404 |
| `ERR_GIFT_ITEM_NOT_FOUND` | 404 |
| `ERR_ARTIST_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_PROOF_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CARD_RETIRED` | 409 |
| `ERR_GIFT_ITEM_RETIRED` | 409 |
| `ERR_ADDRESS_NOT_VERIFIED` | 409 |
| `ERR_PROOF_NOT_APPROVED` | 409 |
| `ERR_ARTIST_NOT_ASSIGNED` | 409 |
| `ERR_SEND_DATE_IN_PAST` | 422 |
| `ERR_TOO_EARLY_TO_PRODUCE` | 409 |
| `ERR_ARTIST_WINDOW_CONFLICT` | 409 |
| `ERR_REMINDER_WINDOW_OVERLAP` | 409 |
| `ERR_ARTIST_CAPACITY_EXCEEDED` | 409 |
| `ERR_GIFT_QUANTITY_INVALID` | 422 |
| `ERR_EMPTY_IMPORT` | 422 |
| `ERR_AUTO_SEND_CARD_REQUIRED` | 422 |
| `ERR_INSUFFICIENT_CREDITS` | 402 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
</content>
</invoke>
