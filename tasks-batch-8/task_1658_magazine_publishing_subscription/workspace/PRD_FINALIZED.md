# Magazine Publishing & Subscription Fulfillment API — Product Requirements Document

## 1. Introduction

A consumer magazine publisher lives and dies by two clocks at once: the production calendar that carries each issue from editorial close through the printer to the mail stream, and the subscription ledger that decides who receives which issue and when the cash they paid becomes earned revenue. Missed ad-close dates, mailing labels generated against a stale subscriber file, Periodical-class mailings that cannot substantiate their paid-circulation share, and renewal revenue recognized before the corresponding issues ship are the classic ways a publishing operation bleeds money or loses its mailing privileges.

This document specifies the Magazine Publishing & Subscription Fulfillment API, the system of record for that operation. It governs the setup of publications and their issue pipelines; the subscriber file and the subscriptions, gift subscriptions, and renewal series built on top of it; mailing batches, label generation, and postal verification; back-issue and single-copy sales; digital edition entitlements; deferred revenue recognition under two distinct accounting variants; and the periodic circulation audits that prove a publication's paid or controlled qualification. Five operator roles share the workload with deliberate segregation of duties, and a controllable logical clock drives every date-sensitive behavior so that production timing, grace periods, and renewal windows are deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operational capacity in which the operator acts. A request in which either header is missing or invalid is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

The system recognizes exactly five roles. `PublishingDirector` is the executive role and owns the publication lifecycle, audit pass/fail adjudication, and clock control. `ProductionManager` owns the issue production pipeline from editorial close to finalization. `CirculationManager` owns the subscriber file, subscriptions, renewal series and events, back-issue order cancellation and refunds, entitlement revocation, and circulation audit preparation. `FulfillmentManager` owns mailing batches, label generation, tendering, issue mailing, and back-issue fulfillment. `PostalComplianceOfficer` owns postal verification and confirmation, deliberately segregated from fulfillment. Section 4 lists, per endpoint, which roles are authorized; an authenticated operator attempting an operation outside their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Every role's identity is opaque. When `X-User-Role` is `PublishingDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the same holds when `X-User-Role` is `ProductionManager`, `CirculationManager`, `FulfillmentManager`, or `PostalComplianceOfficer` — in each case `X-User-ID` is an opaque operator identifier that the server may record but never compares against any entity's `id`. Resource scoping is expressed purely through path hierarchy, never through user identity.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0 and must never be negative. A `limit` outside the range of 1 to 100, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION_PARAMETERS` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The server never consults wall-clock time. Instead it maintains a logical clock, `current_utc`, whose startup default — before it has ever been set — is exactly 2026-08-01T00:00:00Z, and which never falls back to wall-clock time thereafter. A `PublishingDirector` may move the clock through a test-driving capability that accepts a target instant `to_iso8601` and answers with the resulting `current_utc`.

Every date-sensitive rule in this document — editorial and advertising closes, the printer ship date, the mail date, the tender window, grace-period expiry, and renewal-effort windows — compares against this logical clock. Setting the clock forward also triggers any time-based system transitions whose preconditions have become satisfied at the new instant: a subscription whose thirty-day grace period has elapsed moves on to `EXPIRED`, and renewal efforts whose offset windows have opened may fire.

### 2.5. Common Resource Properties

All primary resources — Publications, Issues, Subscribers, Subscriptions, SubscriptionTerms, RenewalSeries, RenewalEvents, MailingBatches, BackIssueOrders, DigitalEntitlements, and CirculationAuditRecords — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every change to the resource.
- `version` (integer): a system-managed integer that increments by exactly one with every modification to the resource. State-transition actions are modifications: every successful lifecycle action on a Publication, Issue, Subscription, MailingBatch, BackIssueOrder, or CirculationAuditRecord refreshes its `updated_at` and increments its `version` by one.

Three resources are immutable ledger-style snapshots and carry only `id` and `created_at`: the MailingLabel, the PostalStatement, and the DeferredRevenueEntry. On these three, both `updated_at` and `version` are absent entirely.

### 2.6. Nested Resource Retrieval

Most resources are addressed through their parent chain — an issue under a publication, a mailing batch under an issue, a subscription under a publication and a subscriber. When an endpoint path contains multiple resource identifiers, the system validates them sequentially from left to right, and the request is rejected immediately with the 404 error belonging to the first identifier that does not resolve: a missing publication yields `ERR_PUBLICATION_NOT_FOUND`; a missing issue within a validated publication yields `ERR_ISSUE_NOT_FOUND`; a missing subscriber yields `ERR_SUBSCRIBER_NOT_FOUND`; a missing subscription yields `ERR_SUBSCRIPTION_NOT_FOUND`; a missing mailing batch yields `ERR_BATCH_NOT_FOUND`; a missing back-issue order yields `ERR_ORDER_NOT_FOUND`; a missing circulation audit yields `ERR_AUDIT_NOT_FOUND`; a missing renewal event yields `ERR_RENEWAL_EVENT_NOT_FOUND`; and a missing renewal series yields `ERR_SERIES_NOT_FOUND`. Child lookups never run before the parent's existence is established, so a request aimed at a batch under a nonexistent issue fails on the issue before the batch is ever considered.

### 2.7. Validation Evaluation Order

When a request violates several rules at once, the error it receives is deterministic, because validations are evaluated in a fixed order. First, the presence and validity of the two context headers is checked. Second, the role's permission to perform the operation. Third, the existence of every path identifier, left to right as described above. Fourth, lifecycle-state permissibility — the resource must be in the state the operation starts from (an issue must be `AD_CLOSED` before it can ship to the printer; a subscription must be `ACTIVE` before it can be suspended); violations surface as `ERR_INVALID_STATE` (HTTP 409) unless a more specific state error is defined for the operation. Fifth, on the three concurrency-guarded writes, the expected-version match described in §2.9. Sixth, date-driven deadline preconditions evaluated against the logical clock. Seventh, referential integrity of gift donors and start issues on subscription creation. Eighth, the consistency between a subscription's qualification tier and its payment details. Ninth, postal-compliance thresholds at verification. Tenth, the advertising-pages requirement at advertising close. Eleventh, the print-run override floor at ship-to-printer. Twelfth, newsstand inventory sufficiency for back-issue orders. Thirteenth, the requirement that no unrecognized deferred revenue remain before a publication ceases. Fourteenth, audit-period sanity and the single-draft audit rule. Fifteenth, the renewal-window check when an effort is fired manually. Sixteenth, pagination parameter bounds on list endpoints. Seventeenth and last, the presence and well-formedness of required input fields — an `issn` of exactly eight characters, a `state_code` of exactly two characters, a `quantity` greater than zero — whose violations surface as `ERR_INVALID_REQUEST` (HTTP 400).

### 2.8. Monetary Precision and Rounding

All monetary amounts in this system are integer counts of cents; no monetary value is ever stored or returned as a fractional quantity. Rounding behavior is pinned per calculation rather than left to convention: per-issue revenue recognition, per-piece postage, gift credits, and back-issue markups round half up to the nearest whole cent; cancellation refunds round down (floor) in the publisher's favor; and paid-share figures expressed in basis points truncate (floor) and are never rounded up. Where a calculation has several steps, intermediate steps are not rounded — postage, in particular, rounds only at its final multiplication step, never at the base-rate lookup. The only non-integer quantity anywhere in the API is `piece_weight_oz`, a decimal number of ounces.

### 2.9. Optimistic Concurrency Control

Exactly three write operations carry optimistic concurrency control; no other endpoint accepts a version field of any kind.

Renewing a subscription requires the request to carry `expected_subscription_version`, holding the `version` of the Subscription as the client last observed it. If the subscription's current `version` has advanced past what the client observed — because a renewal event or an automatic transition has mutated it in the meantime — the renewal is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412), preventing the client from overwriting state it has not seen.

Closing advertising on an issue requires `expected_issue_version`, the client's last observed `version` of the Issue. A mismatch with the issue's current `version` — for example because an editorial update or an `ad_pages_sold` adjustment landed in between — is rejected with `ERR_STALE_ISSUE_VERSION` (HTTP 412).

Generating labels for a mailing batch requires `expected_batch_version`, the client's last observed `version` of the MailingBatch. If another operator has modified batch attributes such as its `postal_class` or `entry_point` since the client last read it, the batch's `version` will have advanced and the request is rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412).

### 2.10. Deferred Revenue Accounting

Cash collected for a subscription term is a liability, not income, until the corresponding issues are served. Every SubscriptionTerm records the cash received as `gross_amount_cents`, the still-unrecognized remainder as `deferred_balance_cents`, and the cumulative recognized portion as `recognized_balance_cents`; while the term stands `OPEN`, the recognized and deferred balances always sum exactly to the gross. Recognition and reversal events are written as immutable DeferredRevenueEntry lines, each naming its owning term via `subscription_term_id` and the issue against which revenue was recognized via `issue_id`, each carrying a signed `amount_cents` — positive for recognition, negative for reversal — a `variant` recording which recognition variant was used, an `entry_type` of `RECOGNITION`, `REVERSAL`, or `REFUND_LIQUIDATION`, and a `recognized_at` timestamp.

Each term pins its recognition variant at birth: `recognition_variant` is a snapshot of the publication's `deferred_revenue_method` taken when the term is created, and it does not change mid-term even if the publication's method is later edited. The two variants, `PRO_RATA_ISSUE` and `STRAIGHT_LINE_MONTH`, recognize the same total over the term but with different per-period timing, and are specified in §3.5. A term whose entire gross has been recognized stands `FULLY_RECOGNIZED`; a cancelled term ends `REFUNDED` or `PARTIALLY_REFUNDED` as described in §3.6. Back-issue sales are the exception to everything in this subsection: their revenue is recognized immediately upon delivery and is never deferred.

### 2.11. Postal Compliance and Segregation of Duties

Mailing privileges hinge on two controls the API treats as structural. First, the compliance thresholds: a batch mailing at the `PERIODICAL` class must show a paid share of at least fifty percent of its pieces and an advertising share of at most seventy-five percent of the issue's pages, and a `STANDARD`-class batch must not carry controlled (free) copies at all. Second, segregation of duties: the operator who builds and tenders a mailing (`FulfillmentManager`) is never the operator who verifies its compliance or confirms its acceptance (`PostalComplianceOfficer`). The PostalStatement produced at verification is an immutable snapshot, so the figures a mailing was verified against cannot drift after the fact. As an early-warning control, whenever verification of a `PAID` publication's batch reveals a paid share below seventy percent, the publication is flagged for audit.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Publication and Its Issue Pipeline

A `PublishingDirector` brings a title into the system by creating a **Publication** with its `title`, its eight-character `issn`, a `frequency` of `WEEKLY`, `MONTHLY`, or `QUARTERLY`, a `circulation_model` of `PAID`, `CONTROLLED`, or `MIXED`, and the `base_cover_price_cents` that anchors single-copy pricing. The publisher may optionally declare the publication's `deferred_revenue_method` — `PRO_RATA_ISSUE` or `STRAIGHT_LINE_MONTH` — which defaults to `PRO_RATA_ISSUE` when omitted and governs how subscription cash becomes earned revenue (§2.10). From the declared frequency the system derives `issues_per_year`: fifty-two for a weekly, twelve for a monthly, four for a quarterly. A new publication begins life `ACTIVE`.

Within a publication, a `ProductionManager` lays out the production calendar one **Issue** at a time. Each issue is created with its `issue_number` and `volume_number`, the `cover_date` that will appear on the masthead, and the four production deadlines: `editorial_close_date`, `ad_close_date`, `ship_to_printer_date`, and `mail_date` — the scheduled USPS tender date. The advertising close must not fall before the editorial close. Three optional quantities complete the issue's creation payload: `ad_pages_sold`, the count of advertising pages sold, defaulting to zero; `print_run_override`, defaulting to unset, which pins the final print quantity when present; and `newsstand_buffer_copies`, the single-copy buffer added to the print run, also defaulting to zero. An issue is born into `PLANNING` and walks the pipeline `PLANNING → EDITORIAL_CLOSED → AD_CLOSED → AT_PRINTER → MAILED → FINALIZED`, with a single permitted retreat from `AD_CLOSED` back to `EDITORIAL_CLOSED`.

### 3.2. Building the Subscriber File: Registration, Subscriptions, and Gifts

Before anything can be mailed, a `CirculationManager` registers a **Subscriber** with `email`, `full_name`, and a mailing address composed of `address_line1`, an optional `address_line2`, `city`, a two-character `state_code`, and a `postal_code`. The `country_code` defaults to `US` when omitted; a non-US address is treated as foreign for mailing-batch splitting and for back-issue shipping. A subscriber's `email` must be unique per publication. At registration the subscriber is assumed reachable — `is_deliverable` starts true — and stands outside any circulation qualification, with `circulation_class` equal to `NON_QUALIFIED`. Postal hygiene may later flip deliverability: an address found invalid under USPS CASS, or appearing on NCOA suppression, renders `is_deliverable` false. A `CirculationManager` may also update any of the six address fields on an existing subscriber; when an update leaves the `postal_code` invalid, `is_deliverable` flips to false.

A **Subscription** ties a subscriber to a publication. Creating one names the `start_issue_id` — the first issue to be served, which must identify an issue belonging to that publication and not one already `MAILED` or `FINALIZED`, failing which the creation is rejected with `ERR_INVALID_START_ISSUE` — together with the `term_issues` count (twelve for a one-year term on a monthly, for instance), the `price_paid_cents` collected for the term, and a `qualification_tier` of `PAID`, `CONTROLLED`, or `COMPLIMENTARY`. Four optional fields complete the payload. The `payment_method` is `CARD`, `CHECK`, `INVOICE`, or `NONE`, defaulting to `CARD`; `NONE` is permitted only when the tier is `CONTROLLED` or `COMPLIMENTARY`. The `is_gift` flag, defaulting to false, marks the subscription as a gift, and exactly when it is true a `donor_subscriber_id` must be present naming the donor. The `auto_renew` flag, defaulting to false, requests automatic renewal at expiry, and `expire_action` — `EXPIRE` by default, or `CONVERT_TO_CONTROLLED` — selects what happens at natural term end. A freshly created subscription sits in `PENDING_START`. Tier-and-payment consistency is enforced already at creation — a `PAID` subscription created with a `price_paid_cents` of zero or a `payment_method` of `NONE` is rejected with `ERR_PAID_REQUIRES_PAYMENT`, and a `CONTROLLED` subscription created with a nonzero price is rejected with `ERR_CONTROLLED_MUST_BE_FREE` — and the same rules guard activation, as described below.

Gift subscriptions carry a donor-side benefit. When a subscription is created with `is_gift` true and the named donor holds an active `PAID` subscription on the same publication, the donor's `OPEN` term receives a credit equal to ten percent of the gift's `price_paid_cents`, rounded half up to whole cents and capped at the donor term's remaining `deferred_balance_cents`. The credit posts as a `RECOGNITION` entry on the donor's term, stamped with the donor term's own `recognition_variant`, and moves the credit amount from the donor's `deferred_balance_cents` into their `recognized_balance_cents`. A `donor_subscriber_id` that names no subscriber, or one whose owner has no active paid subscription on the publication, is rejected with `ERR_DONOR_NOT_FOUND` (HTTP 404).

Activation is where a subscription becomes real. A `CirculationManager` activates a `PENDING_START` subscription, moving it to `ACTIVE`, under four guards evaluated against the publication, the tier, and the address: the publication must be `ACTIVE`, else `ERR_PUBLICATION_NOT_ACTIVE`; a `PAID` tier requires a positive `price_paid_cents` and a `payment_method` other than `NONE`, else `ERR_PAID_REQUIRES_PAYMENT`; a `CONTROLLED` tier requires `price_paid_cents` of exactly zero, else `ERR_CONTROLLED_MUST_BE_FREE`; and the subscriber must be deliverable, else `ERR_UNDELIVERABLE_ADDRESS`. Activation creates the first **SubscriptionTerm** with `term_index` 1, its `term_start_issue_id` equal to the subscription's start issue, `issues_in_term` equal to `term_issues`, `gross_amount_cents` and `deferred_balance_cents` both equal to the price paid, and `recognition_variant` snapshotted from the publication's current `deferred_revenue_method`. The term's `term_end_issue_id` is computed as the issue `term_issues` minus one sequential issues after the start issue. Activation also re-derives the subscriber's `circulation_class`: a `PAID` tier promotes the subscriber to `PAID_QUALIFIED`, while `CONTROLLED` and `COMPLIMENTARY` tiers make them `CONTROLLED_QUALIFIED`. Finally, when the publication has a default renewal series, the subscription adopts that series' code as its `renewal_series_code` and its first renewal effort is scheduled; the `renewal_effort_number` counter starts at zero, meaning no effort has yet been sent.

Two counters track service against the term: `issues_served`, the number of issues already mailed to the subscription within the current term, and `issues_suspended_count`, the number of issues skipped while the subscription was suspended. From these the system derives `issues_remaining` as `term_issues` minus `issues_served` minus `issues_suspended_count`, never below zero.

### 3.3. Issue Production: From Editorial Close to the Printer

Once the logical clock has reached an issue's `editorial_close_date`, a `ProductionManager` closes editorial, moving the issue from `PLANNING` to `EDITORIAL_CLOSED`; attempting it earlier is rejected with `ERR_EDITORIAL_NOT_CLOSED_YET`, and attempting it on a publication that is not `ACTIVE` fails with `ERR_PUBLICATION_NOT_ACTIVE`.

Closing advertising moves the issue from `EDITORIAL_CLOSED` to `AD_CLOSED` and is one of the three concurrency-guarded writes: the request must carry `expected_issue_version`, and a stale value is rejected with `ERR_STALE_ISSUE_VERSION` as §2.9 describes. The close is allowed only once the logical clock has reached the `ad_close_date` — earlier attempts fail with `ERR_AD_CLOSE_NOT_REACHED` — and only when the issue has advertising content: `ad_pages_sold` must be greater than zero, except on a `CONTROLLED` publication, which may close with zero ads. A `PAID` or `MIXED` publication closing with no ad pages is rejected with `ERR_NO_AD_PAGES`. Closing freezes `ad_pages_sold`: from `AD_CLOSED` onward, further edits to it are rejected with `ERR_AD_CLOSE_LOCKED`.

Should advertising need to reopen — a late insertion order, a correction — a `ProductionManager` may revert the issue from `AD_CLOSED` back to `EDITORIAL_CLOSED`, which unfreezes `ad_pages_sold`. The retreat is available only while every mailing batch on the issue still sits in `DRAFT`; once any batch has moved forward, reopening is rejected with `ERR_BATCH_ALREADY_GENERATED`.

Shipping to the printer moves the issue from `AD_CLOSED` to `AT_PRINTER` and is allowed once the logical clock has reached the `ship_to_printer_date` (`ERR_PRINTER_DATE_NOT_REACHED` otherwise). This is the moment the print quantity is fixed. The system computes `qualified_subscriber_count` as the number of subscriptions on the publication that are `ACTIVE`, belong to a deliverable subscriber, started no later than this issue in the publication's sequence, and still have issues remaining. The final `print_run` is then either the `print_run_override`, when one was set — an override smaller than the qualified count is rejected with `ERR_PRINT_RUN_TOO_SMALL` — or, with no override, the `qualified_subscriber_count` plus the issue's `newsstand_buffer_copies`.

### 3.4. Mailing Batches, Label Generation, and Postal Verification

With an issue at the printer, a `FulfillmentManager` carves the mailing into **MailingBatch** resources, each created with a human-readable `batch_label` such as `DOMESTIC`, `FOREIGN`, or `NEWSSTAND`, a `postal_class` of `PERIODICAL`, `STANDARD`, or `FIRST_CLASS`, and the USPS `permit_number` under which it mails. The `entry_point` — `ORIGIN`, `DDU`, `DSCF`, or `SCF`, defaulting to `ORIGIN` — records the drop-ship entry point, and `is_controlled_copy_included`, defaulting to true, declares whether controlled copies ride the batch. A batch begins in `DRAFT`.

Label generation moves a batch from `DRAFT` to `LABELS_GENERATED` and is the third concurrency-guarded write, requiring `expected_batch_version` with mismatches rejected as `ERR_STALE_BATCH_VERSION`. It runs only while the issue is `AT_PRINTER` — any other issue state yields `ERR_ISSUE_NOT_AT_PRINTER` — and only once per batch, a second attempt failing with `ERR_LABELS_ALREADY_GENERATED`. Generation writes one **MailingLabel** per subscription that is `ACTIVE`, belongs to the issue's publication, still has issues remaining, and belongs to a deliverable subscriber — subscriptions in suspension are skipped — subject to the batch's inclusion rule: a `DOMESTIC` batch takes subscribers whose `country_code` is `US`, a `FOREIGN` batch takes non-US subscribers, and a `NEWSSTAND` batch takes no subscriptions at all, since newsstand copies are not addressed to subscribers. Every label snapshots the recipient's `address_block` (the formatted multi-line mailing address at generation time) and `postal_code` (the ZIP+4 at generation time), records the owning batch via `batch_id`, the served subscription via `subscription_id`, and the recipient via `subscriber_id` (denormalized for sortation), marks `is_controlled_copy` true when the subscription's tier at generation is `CONTROLLED` or `COMPLIMENTARY`, and carries the `piece_weight_oz` used for rating. Each label's `postage_cents` is computed by the postal-rate calculation below, and the batch then records `expected_piece_count` as the number of labels written and `total_postage_cents` as their summed postage.

Per-piece postage is a function of the batch's `postal_class`, its `entry_point`, the label's `piece_weight_oz`, and whether the piece is a controlled copy, with the base rate looked up from weight tiers:

- A `PERIODICAL` piece costs 28 cents when it weighs at most 3.3 ounces, 41 cents when it weighs more than 3.3 and at most 6.0 ounces, and 58 cents when it weighs more than 6.0 and at most 10.0 ounces; beyond 10.0 ounces, the base is 58 cents plus 7 cents for each additional ounce or fraction of an ounce past 10.0, the excess weight being rounded up to a whole ounce.
- A `STANDARD` piece costs 52 cents at up to 3.3 ounces and 74 cents when it weighs more than 3.3 and at most 6.0 ounces; beyond 6.0 ounces, the base is 74 cents plus 11 cents for each additional ounce or fraction of an ounce past 6.0.
- A `FIRST_CLASS` piece costs 68 cents at up to 1.0 ounce, 92 cents when it weighs more than 1.0 and at most 2.0 ounces, and 116 cents when it weighs more than 2.0 and at most 3.0 ounces; beyond 3.0 ounces, the base is 116 cents plus 24 cents for each additional ounce or fraction of an ounce past 3.0.

Drop-ship entry then earns a discount on the base: twenty-one percent at `DDU`, thirteen percent at `DSCF`, seven percent at `SCF`, and none at `ORIGIN`. A controlled copy mailed under `PERIODICAL` class instead pays a five percent surcharge; no other class carries it. The label's `postage_cents` is the base multiplied by ten thousand minus the discount's basis points plus the surcharge's basis points, divided by ten thousand, and rounded half up to a whole number of cents. Rounding happens only at this final multiplication — never at the base-rate lookup.

Verification moves the batch from `LABELS_GENERATED` to `POSTAL_VERIFIED` and belongs exclusively to the `PostalComplianceOfficer`. For a `PERIODICAL` batch, two thresholds bind: the paid share of its pieces must reach at least fifty percent — 5000 basis points — or verification is rejected with `ERR_PAID_RATIO_BELOW_MINIMUM`, and the issue's advertising share must not exceed seventy-five percent — 7500 basis points — or it is rejected with `ERR_AD_CONTENT_EXCEEDS_LIMIT`. For a `STANDARD` batch, controlled copies are forbidden outright: if `is_controlled_copy_included` is true, verification fails with `ERR_STANDARD_NO_CONTROLLED`. A successful verification writes an immutable **PostalStatement** snapshot against the batch (via `batch_id`) whose `form_number` derives from the `postal_class` and takes one of `PS_3541`, `PS_3541_A`, or `PS_3602_R`. The statement records `paid_piece_count` — the labels whose `is_controlled_copy` is false — and `controlled_piece_count` — those where it is true — and expresses the paid share as `paid_percentage_bps`: the paid piece count multiplied by ten thousand and divided by the total piece count, truncated to a whole number of basis points, and defined as zero when there are no pieces at all. It likewise records the issue's `advertising_percentage_bps` — the share of the issue's total page count represented by its `ad_pages_sold`, in basis points — and mirrors the batch's `total_postage_cents` as it stood at filing, stamped with the immutable `filed_at` instant. Wherever a paid share in basis points is needed in this system — on the postal statement or at audit time — it is computed by this same truncate-to-basis-points rule. As an early warning, verifying a `PAID` publication's batch whose paid share falls below seventy percent flags the publication for audit.

Tendering — moving the batch from `POSTAL_VERIFIED` to `TENDERED` — returns to the `FulfillmentManager` and may happen no earlier than one day before the issue's `mail_date`; an earlier tender is rejected with `ERR_TENDER_TOO_EARLY`. Finally, the `PostalComplianceOfficer` confirms the mailing, moving the batch from `TENDERED` to `CONFIRMED` and marking it immutable — the counterpart to the fulfillment tender, keeping the two duties in separate hands per §2.11.

### 3.5. Mailing Day: Serving Issues and Recognizing Revenue

Marking an issue mailed — `AT_PRINTER → MAILED`, performed by a `FulfillmentManager` — is the system's pivotal event. It is blocked until every mailing batch on the issue stands `CONFIRMED` (`ERR_BATCH_NOT_CONFIRMED` otherwise) and until the logical clock has reached the `mail_date` (`ERR_MAIL_DATE_NOT_REACHED` otherwise). Every subscription served by the issue — the `ACTIVE` subscriptions with issues remaining for which a label was generated — then has its `issues_served` incremented by one and its `issues_remaining` decremented by one.

Mailing is also the recognition event for deferred revenue. For each served subscription's `OPEN` term, the system posts a DeferredRevenueEntry according to the term's pinned variant. Under `PRO_RATA_ISSUE`, each issue of the term recognizes the term's `gross_amount_cents` divided by `issues_in_term`, rounded half up to whole cents — except the term's final issue, identified when the count of `RECOGNITION` entries already posted against the term has reached one less than `issues_in_term`, which instead recognizes whatever amount remains so that `recognized_balance_cents` and `deferred_balance_cents` together equal `gross_amount_cents` exactly. Each recognition posts an entry with `entry_type` `RECOGNITION` and `variant` `PRO_RATA_ISSUE`, increases `recognized_balance_cents`, and decreases `deferred_balance_cents` by the same amount, with `recognized_at` set to the issue's `mail_date`. The issue's `revenue_recognized_cents` records the sum of the recognition entries posted against it.

Under the alternative `STRAIGHT_LINE_MONTH` variant, recognition spreads evenly across the calendar months the term spans rather than tracking individual issues, and runs as a month-end pass over every `OPEN` term whose `recognition_variant` is `STRAIGHT_LINE_MONTH` and whose term covers the closing month, with `recognized_at` set to month-end. The span in months derives from the publication's `frequency`: a `WEEKLY` publication is treated as four issues per month, so the span is the term's `issues_in_term` divided by four and rounded up; a `MONTHLY` publication spans exactly `issues_in_term` months; a `QUARTERLY` publication's issues each cover three months, so the span is `issues_in_term` multiplied by three. Each month recognizes the term's `gross_amount_cents` divided by the span, rounded down to whole cents, and the final month additionally recognizes the residual, so that the full gross is recognized across the span.

A subscription whose `issues_remaining` reaches zero at mailing arrives at the end of its term. Ordinarily it enters `GRACE`; but when its `auto_renew` flag is true, the grace period is skipped and the subscription moves directly to `RENEWED` through the auto-renew path, with a new SubscriptionTerm created automatically for the next term. For every served subscription with `is_gift` true, mailing additionally creates a **DigitalEntitlement** for the recipient with `access_level` `FULL` and `granted_at` set at that moment; `revoked_at` and `revocation_reason` stay unset while the entitlement is active.

Once the mail has gone, a `ProductionManager` finalizes the issue, moving it from `MAILED` to `FINALIZED`. Finalization carries a reconciliation gate: every served subscription must have had its DeferredRevenueEntries posted. A finalized issue is locked against any further state change and is terminal.

### 3.6. The Subscription Journey: Suspension, Renewal, Grace, and Cancellation

Between activation and expiry, a subscription may pause. A `CirculationManager` suspends an `ACTIVE` subscription — permitted only while the publication itself is `ACTIVE`, since a suspended publication has already carried its subscriptions down with it. While `SUSPENDED`, no issues are served: label generation skips the subscription, and pending renewal events stay `PENDING` but are not acted on. Resuming returns the subscription from `SUSPENDED` to `ACTIVE`, again guarded by the publication being `ACTIVE` (`ERR_PUBLICATION_NOT_ACTIVE`) and by the subscriber being deliverable (`ERR_UNDELIVERABLE_ADDRESS`). At resume time the system counts the issues missed during the suspension, increments `issues_suspended_count` by that number, and recomputes `issues_remaining`; missed issues are neither refunded nor credited.

Renewal marketing is driven by a **RenewalSeries** configured per publication: a `series_code` such as `STD3` or `PREMIUM5`, an ordered `effort_offsets_days` array of day offsets before expiry at which efforts fire (for example ninety, sixty, thirty, and seven days ahead, expressed as negative offsets), and a parallel `effort_pricing_cents` array giving the renewal price offered at each effort, which must have the same length as the offsets array. The series' `max_efforts` is the number of offsets, and at most one series per publication may carry `is_default` true. When an effort fires for a subscription, the created **RenewalEvent** takes the next `effort_number` — one greater than the subscription's current `renewal_effort_number` — records `sent_at`, and sets its `offered_price_cents` to the entry of `effort_pricing_cents` at that effort's position: the first effort uses the first price, the second the second, and no event fires once the effort number would exceed `max_efforts`. The event's `series_code` is denormalized onto it for audit, its `response` starts `PENDING`, and `responded_at` remains unset until the subscriber answers. An effort may fire only when the logical clock has crossed the effort's configured offset window ahead of expiry; a `CirculationManager` may fire the next effort manually, but doing so before its window has opened is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`. For the purpose of this window, the subscription's expiry is projected as follows. While the subscription is in `GRACE`, its expiry is the instant it entered grace plus the thirty-day grace period. Before grace, when the open term's `term_end_issue_id` resolves to a known issue, expiry is that issue's scheduled `mail_date` plus the thirty-day grace period. When the publication's issue sequence does not yet extend to the term's end issue, so that `term_end_issue_id` is unresolved, expiry is instead projected from the subscription's start issue's scheduled `mail_date`, plus the term's span converted to days — the subscription's `term_issues` multiplied by 365 and divided by the publication's `issues_per_year`, rounded up to a whole day — plus the thirty-day grace period. From `PENDING`, an event resolves one of three ways: a successful renewal matching the effort marks it `ACCEPTED`; a `CirculationManager` may mark it `DECLINED`, which also increments the subscription's `renewal_effort_number`; and the event lapses to `EXPIRED` when the next effort fires or when the subscription cancels or expires.

When a served subscription's `issues_remaining` reaches zero and it is not set to auto-renew, it enters `GRACE`. Thirty days after entering grace — measured against the logical clock — the subscription lapses to `EXPIRED`; any renewal event still `PENDING` is expired with it. A subscription whose `expire_action` is `CONVERT_TO_CONTROLLED` does not simply die at this point: expiry regenerates it cyclically as a brand-new subscription with `qualification_tier` `CONTROLLED`, zero `price_paid_cents`, and status `ACTIVE`.

A subscriber in grace may also be won back explicitly. A `CirculationManager` renews a `GRACE` subscription — a concurrency-guarded write requiring `expected_subscription_version`, rejected with `ERR_STALE_SUBSCRIPTION_VERSION` when stale — supplying the new term's `new_term_issues` and `new_price_paid_cents`; renewal requires payment to have been accepted for the renewal term, with a positive price recorded. Renewal creates a new SubscriptionTerm whose `term_index` increments by one from the previous term and whose `recognition_variant` is re-snapshotted from the publication's current `deferred_revenue_method`; it resets `issues_served` to zero and sets `issues_remaining` to the new term's issue count; it marks the most recent `PENDING` renewal event `ACCEPTED`; and it returns the subscription to `ACTIVE` immediately — the `RENEWED` outcome stands as the terminal marker on the old term while the new term drives the subscription forward.

Cancellation, by contrast, is a `CirculationManager` action on an `ACTIVE` subscription that moves it to the terminal `CANCELLED` state and unwinds the money. The refund is computed from the cancelled term's remaining `deferred_balance_cents`: when no issues have been served, the entire balance is refunded; when one, two, or three issues have been served, ninety percent of the balance; when more than three have been served, fifty percent. The refunded amount is the balance multiplied by the applicable rate, rounded down to whole cents. The unrefunded remainder is recognized immediately as a `RECOGNITION` entry, and a second entry of type `REFUND_LIQUIDATION` for the negative of the entire remaining deferred balance — the same remaining `deferred_balance_cents` the refund was computed from, as it stood before the unrefunded remainder's recognition reduced it — zeroes out the liability. The term is then marked `REFUNDED` when the full balance was refunded, or `PARTIALLY_REFUNDED` otherwise. Cancellation also expires every `PENDING` renewal event on the subscription, revokes all of its DigitalEntitlements with `revocation_reason` `REFUND`, and recomputes the subscriber's `circulation_class` — a subscriber left with no other active subscriptions falls back to `NON_QUALIFIED`.

### 3.7. Back-Issue Sales and Digital Edition Entitlements

Single-copy demand does not end with the mail stream. Either a `CirculationManager` or a `FulfillmentManager` may place a **BackIssueOrder** for a subscriber, naming the `issue_id` being ordered and a `quantity` greater than zero; the order is born `PENDING`. Pricing snapshots the publication's `base_cover_price_cents` at order time into `unit_price_cents`, with a markup for age: when the issue's `cover_date` lies more than twelve months in the past, the unit price is one and a half times the base, rounded half up to whole cents; otherwise it is the base price unchanged. A flat `shipping_cents` is computed from the destination `country_code`, and `total_charged_cents` is the quantity times the unit price plus shipping. Newsstand supply is finite: the available inventory for an issue is its `newsstand_buffer_copies` less the copies already sold, and an order whose quantity exceeds the available inventory is rejected with `ERR_INSUFFICIENT_INVENTORY` — a check enforced both when the order is placed and again when it is fulfilled.

Fulfillment walks the order through `PENDING → FULFILLED → SHIPPED → DELIVERED`, each step taken by a `FulfillmentManager`. Fulfilling requires the issue to be `FINALIZED` (`ERR_ISSUE_NOT_FINALIZED` otherwise) and sufficient remaining inventory, and it decrements the issue's available newsstand inventory. Shipping and delivery follow without further conditions, and at delivery `is_recognized_revenue` flips to true: back-issue revenue is recognized immediately, never deferred per §2.10. Two exits branch off the walk. A `CirculationManager` may cancel an order still `PENDING`, leaving it `CANCELLED`. Once delivered, a `CirculationManager` may instead refund the order, moving it from `DELIVERED` to `REFUNDED`, returning the full `total_charged_cents`, and putting the copies back into newsstand stock.

Digital entitlements follow the print lifecycle. They are created at mailing time for gift subscriptions as §3.5 describes, with an `access_level` — `FULL`, `PREVIEW`, or `NONE` — derived from the subscription's state at grant time, each recording its `subscription_id`, the `issue_id` it unlocks, and the `granted_at` instant. Beyond the automatic `REFUND` revocation on cancellation, a `CirculationManager` may revoke an entitlement manually, supplying a `reason` of `REFUND`, `CHARGEBACK`, or `MANUAL`; revocation stamps `revoked_at` and records the `revocation_reason`.

### 3.8. Circulation Audits and Publication Wind-Down

Circulation qualification is proven, not asserted. A `CirculationManager` opens a **CirculationAuditRecord** on a publication by giving the six-month audit window's `audit_period_start` and `audit_period_end`; the end must be strictly later than the start (`ERR_INVALID_AUDIT_PERIOD` otherwise), and only one audit per publication may sit in `DRAFT` at a time (`ERR_DRAFT_AUDIT_EXISTS`). While drafted, the record's `qualification_result` is `PENDING`.

Filing the audit — a `CirculationManager` action moving it from `DRAFT` to `FILED` — requires every issue whose `mail_date` falls within the period, start and end inclusive, to be `FINALIZED`; an unfiled pipeline issue in the window is rejected with `ERR_UNFILED_ISSUES_IN_PERIOD`. Filing computes the record's figures: `total_distribution`, the sum of issues mailed during the period; `paid_distribution`, the portion served to `PAID_QUALIFIED` subscribers; `controlled_distribution`, the portion served to `CONTROLLED_QUALIFIED` subscribers; the `paid_percentage_bps` under the truncation rule of §3.4; and the `qualification_result` under the standard qualification rule — a `PAID` publication qualifies when its paid share is at least seventy percent (7000 basis points, the boundary itself qualifying), a `CONTROLLED` publication qualifies when its paid share is at most thirty percent (3000 basis points, again inclusively), and a `MIXED` publication qualifies when its paid share lies between thirty and seventy percent inclusive; anything else is `NON_QUALIFIED`.

Adjudication belongs to the `PublishingDirector`. Marking the audit passed requires a `QUALIFIED` result — anything else draws `ERR_AUDIT_NOT_QUALIFIED` — and moves the record to `AUDIT_PASSED`. Marking it failed requires a `NON_QUALIFIED` result — anything else draws `ERR_AUDIT_NOT_FAILED` — and moves it to `AUDIT_FAILED`, and when the publication's `circulation_model` is `PAID`, failure cascades: the publication is suspended, carrying its subscriptions with it exactly as a manual suspension does.

Suspension and wind-down close the publication's own lifecycle. A `PublishingDirector` suspends an `ACTIVE` publication only when no issue is mid-flight — every issue must be `FINALIZED`, or still early in `PLANNING` or `EDITORIAL_CLOSED`; any issue in `AD_CLOSED`, `AT_PRINTER`, or `MAILED` blocks the suspension with `ERR_ISSUE_PIPELINE_ACTIVE`. Suspension cascades: every `ACTIVE` subscription on the publication moves to `SUSPENDED`, and every `PENDING` renewal event on those subscriptions expires. Resuming returns the publication from `SUSPENDED` to `ACTIVE`, brings its suspended subscriptions back to `ACTIVE`, and recomputes each subscription's `issues_remaining` with no credit for the suspended period. Ceasing a publication is permanent and therefore gated the hardest: all issues must be `FINALIZED` (`ERR_ISSUE_PIPELINE_ACTIVE` otherwise), all subscriptions must already stand in a terminal state — `EXPIRED`, `CANCELLED`, or `RENEWED` — (`ERR_ACTIVE_SUBSCRIPTIONS_REMAIN` otherwise), and every SubscriptionTerm's `deferred_balance_cents` must be zero, since unrecognized liability may not survive the title (`ERR_UNRECOGNIZED_DEFERRED_REVENUE` otherwise). Ceasing moves the publication from `ACTIVE` to the terminal `CEASED` state, and a `CEASED` publication becomes read-only.

## 4. Endpoint Definitions

Operations that create new resources — a publication, an issue, a subscriber, a subscription, a renewal series, a mailing batch, a back-issue order, a circulation audit, or a fired renewal event — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`, as do all list and detail reads. List endpoints accept the pagination parameters `limit` and `offset`; individual lists additionally accept filter parameters drawn from `status`, `subscriber_id`, `publication_id`, `issue_id`, `qualification_tier`, `circulation_class`, `is_deliverable`, `response`, `access_level`, `is_controlled_copy`, `entry_type`, and `variant`, as narrated in §3. Request and response payloads are reconstructed from the §3 narratives.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PublishingDirector |
| POST | `/publications` | Create a Publication | PublishingDirector |
| GET | `/publications` | List Publications | All roles |
| GET | `/publications/{publicationId}` | Get a Publication | All roles |
| POST | `/publications/{publicationId}/suspend` | Suspend a Publication, cascading to its Subscriptions | PublishingDirector |
| POST | `/publications/{publicationId}/resume` | Resume a suspended Publication | PublishingDirector |
| POST | `/publications/{publicationId}/cease` | Cease a Publication permanently | PublishingDirector |
| GET | `/publications/{id}/issues` | List Issues for a Publication (flat alias) | All roles |
| GET | `/publications/{id}/subscriptions` | List Subscriptions for a Publication (flat alias) | PublishingDirector, CirculationManager, FulfillmentManager |
| GET | `/publications/{id}/renewal-series` | List RenewalSeries for a Publication (flat alias) | PublishingDirector, CirculationManager |
| GET | `/publications/{id}/circulation-audits` | List CirculationAuditRecords for a Publication (flat alias) | PublishingDirector, CirculationManager |
| GET | `/publications/{id}/back-issue-orders` | List BackIssueOrders for a Publication (flat alias) | PublishingDirector, CirculationManager, FulfillmentManager |
| POST | `/publications/{publicationId}/issues` | Create an Issue in PLANNING | ProductionManager |
| GET | `/publications/{publicationId}/issues` | List Issues for a Publication | All roles |
| GET | `/publications/{publicationId}/issues/{issueId}` | Get an Issue | All roles |
| POST | `/publications/{publicationId}/issues/{issueId}/close-editorial` | Close editorial (PLANNING → EDITORIAL_CLOSED) | ProductionManager |
| POST | `/publications/{publicationId}/issues/{issueId}/close-ads` | Close advertising (EDITORIAL_CLOSED → AD_CLOSED); OCC on Issue version | ProductionManager |
| POST | `/publications/{publicationId}/issues/{issueId}/reopen-ads` | Re-open advertising (AD_CLOSED → EDITORIAL_CLOSED) | ProductionManager |
| POST | `/publications/{publicationId}/issues/{issueId}/ship-to-printer` | Ship to printer (AD_CLOSED → AT_PRINTER); computes print run | ProductionManager |
| POST | `/publications/{publicationId}/issues/{issueId}/mark-mailed` | Mark issue mailed (AT_PRINTER → MAILED); triggers revenue recognition | FulfillmentManager |
| POST | `/publications/{publicationId}/issues/{issueId}/finalize` | Finalize an issue (MAILED → FINALIZED) | ProductionManager |
| GET | `/issues/{issueId}` | Get an Issue (flat detail) | All roles |
| GET | `/issues/{id}/mailing-batches` | List MailingBatches for an Issue (flat alias) | PublishingDirector, ProductionManager, FulfillmentManager, PostalComplianceOfficer |
| GET | `/issues/{id}/subscriptions` | List Subscriptions whose start issue is this Issue | PublishingDirector, CirculationManager |
| GET | `/issues/{id}/subscription-terms` | List SubscriptionTerms that start or end at this Issue | PublishingDirector, CirculationManager |
| GET | `/issues/{id}/back-issue-orders` | List BackIssueOrders for an Issue (flat alias) | PublishingDirector, CirculationManager, FulfillmentManager |
| GET | `/issues/{id}/digital-entitlements` | List DigitalEntitlements granted for an Issue | PublishingDirector, CirculationManager |
| GET | `/issues/{id}/deferred-revenue-entries` | List DeferredRevenueEntries recognized against an Issue | PublishingDirector, CirculationManager |
| POST | `/subscribers` | Register a Subscriber | CirculationManager |
| GET | `/subscribers` | List Subscribers | PublishingDirector, CirculationManager, FulfillmentManager |
| GET | `/subscribers/{subscriberId}` | Get a Subscriber | PublishingDirector, CirculationManager, FulfillmentManager |
| PATCH | `/subscribers/{subscriberId}` | Update a subscriber's address; may flip deliverability | CirculationManager |
| GET | `/subscribers/{id}/subscriptions` | List Subscriptions owned by a Subscriber (flat alias) | PublishingDirector, CirculationManager |
| GET | `/subscribers/{id}/back-issue-orders` | List BackIssueOrders placed by a Subscriber (flat alias) | PublishingDirector, CirculationManager, FulfillmentManager |
| GET | `/subscribers/{id}/mailing-labels` | List MailingLabels addressed to a Subscriber | PublishingDirector, FulfillmentManager, PostalComplianceOfficer |
| POST | `/publications/{publicationId}/subscribers/{subscriberId}/subscriptions` | Create a Subscription for a Subscriber on a Publication | CirculationManager |
| GET | `/publications/{publicationId}/subscriptions` | List Subscriptions for a Publication (filterable) | PublishingDirector, CirculationManager, FulfillmentManager |
| GET | `/publications/{publicationId}/subscriptions/{subscriptionId}` | Get a Subscription | PublishingDirector, CirculationManager, FulfillmentManager |
| GET | `/subscribers/{subscriberId}/subscriptions` | List Subscriptions owned by a Subscriber | PublishingDirector, CirculationManager |
| POST | `/publications/{publicationId}/subscriptions/{subscriptionId}/activate` | Activate a Subscription (PENDING_START → ACTIVE); creates the first term | CirculationManager |
| POST | `/publications/{publicationId}/subscriptions/{subscriptionId}/suspend` | Suspend a Subscription (ACTIVE → SUSPENDED) | CirculationManager |
| POST | `/publications/{publicationId}/subscriptions/{subscriptionId}/resume` | Resume a suspended Subscription (SUSPENDED → ACTIVE) | CirculationManager |
| POST | `/publications/{publicationId}/subscriptions/{subscriptionId}/renew` | Renew a Subscription in grace; OCC on Subscription version | CirculationManager |
| POST | `/publications/{publicationId}/subscriptions/{subscriptionId}/cancel` | Cancel a Subscription (ACTIVE → CANCELLED); posts refund | CirculationManager |
| GET | `/subscriptions/{subscriptionId}` | Get a Subscription (flat detail) | PublishingDirector, CirculationManager, FulfillmentManager |
| GET | `/subscriptions/{id}/subscription-terms` | List SubscriptionTerms for a Subscription (flat alias) | PublishingDirector, CirculationManager |
| GET | `/subscriptions/{id}/renewal-events` | List RenewalEvents for a Subscription (flat alias) | PublishingDirector, CirculationManager |
| GET | `/subscriptions/{id}/digital-entitlements` | List DigitalEntitlements for a Subscription (flat alias) | PublishingDirector, CirculationManager |
| GET | `/subscriptions/{id}/mailing-labels` | List MailingLabels generated for a Subscription | PublishingDirector, FulfillmentManager, PostalComplianceOfficer |
| GET | `/publications/{publicationId}/subscriptions/{subscriptionId}/terms` | List SubscriptionTerms for a Subscription | PublishingDirector, CirculationManager |
| GET | `/publications/{publicationId}/subscriptions/{subscriptionId}/terms/{termId}` | Get a SubscriptionTerm | PublishingDirector, CirculationManager |
| GET | `/publications/{publicationId}/subscriptions/{subscriptionId}/terms/{termId}/revenue-entries` | List DeferredRevenueEntries for a SubscriptionTerm | PublishingDirector, CirculationManager |
| GET | `/subscription-terms/{termId}` | Get a SubscriptionTerm (flat detail) | PublishingDirector, CirculationManager |
| GET | `/subscription-terms/{id}/deferred-revenue-entries` | List DeferredRevenueEntries for a SubscriptionTerm (flat alias) | PublishingDirector, CirculationManager |
| POST | `/publications/{publicationId}/renewal-series` | Create a RenewalSeries | CirculationManager |
| GET | `/publications/{publicationId}/renewal-series` | List RenewalSeries for a Publication | PublishingDirector, CirculationManager |
| GET | `/publications/{publicationId}/renewal-series/{seriesId}` | Get a RenewalSeries | PublishingDirector, CirculationManager |
| GET | `/renewal-series/{seriesId}` | Get a RenewalSeries (flat detail) | PublishingDirector, CirculationManager |
| GET | `/publications/{publicationId}/subscriptions/{subscriptionId}/renewal-events` | List RenewalEvents for a Subscription | PublishingDirector, CirculationManager |
| GET | `/publications/{publicationId}/subscriptions/{subscriptionId}/renewal-events/{eventId}` | Get a RenewalEvent | PublishingDirector, CirculationManager |
| POST | `/publications/{publicationId}/subscriptions/{subscriptionId}/renewal-events/fire-next` | Manually fire the next renewal effort | CirculationManager |
| POST | `/publications/{publicationId}/subscriptions/{subscriptionId}/renewal-events/{eventId}/decline` | Mark a RenewalEvent DECLINED | CirculationManager |
| GET | `/renewal-events/{eventId}` | Get a RenewalEvent (flat detail) | PublishingDirector, CirculationManager |
| POST | `/publications/{publicationId}/issues/{issueId}/mailing-batches` | Create a MailingBatch in DRAFT | FulfillmentManager |
| GET | `/publications/{publicationId}/issues/{issueId}/mailing-batches` | List MailingBatches for an Issue | PublishingDirector, ProductionManager, FulfillmentManager, PostalComplianceOfficer |
| GET | `/publications/{publicationId}/issues/{issueId}/mailing-batches/{batchId}` | Get a MailingBatch | PublishingDirector, ProductionManager, FulfillmentManager, PostalComplianceOfficer |
| POST | `/publications/{publicationId}/issues/{issueId}/mailing-batches/{batchId}/generate-labels` | Generate MailingLabels (DRAFT → LABELS_GENERATED); OCC on batch version | FulfillmentManager |
| POST | `/publications/{publicationId}/issues/{issueId}/mailing-batches/{batchId}/verify-postal` | Verify postal compliance (LABELS_GENERATED → POSTAL_VERIFIED); creates the statement | PostalComplianceOfficer |
| POST | `/publications/{publicationId}/issues/{issueId}/mailing-batches/{batchId}/tender` | Tender the batch to USPS (POSTAL_VERIFIED → TENDERED) | FulfillmentManager |
| POST | `/publications/{publicationId}/issues/{issueId}/mailing-batches/{batchId}/confirm` | Confirm USPS acceptance (TENDERED → CONFIRMED) | PostalComplianceOfficer |
| GET | `/mailing-batches/{batchId}` | Get a MailingBatch (flat detail) | PublishingDirector, ProductionManager, FulfillmentManager, PostalComplianceOfficer |
| GET | `/mailing-batches/{id}/mailing-labels` | List MailingLabels for a MailingBatch (flat alias) | PublishingDirector, FulfillmentManager, PostalComplianceOfficer |
| GET | `/mailing-batches/{id}/postal-statements` | List PostalStatements for a MailingBatch (flat alias) | PublishingDirector, PostalComplianceOfficer |
| GET | `/publications/{publicationId}/issues/{issueId}/mailing-batches/{batchId}/labels` | List MailingLabels for a MailingBatch | PublishingDirector, FulfillmentManager, PostalComplianceOfficer |
| GET | `/publications/{publicationId}/issues/{issueId}/mailing-batches/{batchId}/labels/{labelId}` | Get a MailingLabel | PublishingDirector, FulfillmentManager, PostalComplianceOfficer |
| GET | `/mailing-labels/{labelId}` | Get a MailingLabel (flat detail) | PublishingDirector, FulfillmentManager, PostalComplianceOfficer |
| GET | `/publications/{publicationId}/issues/{issueId}/mailing-batches/{batchId}/postal-statements` | List PostalStatements for a MailingBatch | PublishingDirector, PostalComplianceOfficer |
| GET | `/postal-statements/{statementId}` | Get a PostalStatement (flat detail) | PublishingDirector, PostalComplianceOfficer |
| POST | `/publications/{publicationId}/subscribers/{subscriberId}/back-issue-orders` | Place a BackIssueOrder | CirculationManager, FulfillmentManager |
| GET | `/publications/{publicationId}/back-issue-orders` | List BackIssueOrders for a Publication | PublishingDirector, CirculationManager, FulfillmentManager |
| GET | `/subscribers/{subscriberId}/back-issue-orders` | List BackIssueOrders placed by a Subscriber | PublishingDirector, CirculationManager, FulfillmentManager |
| GET | `/publications/{publicationId}/back-issue-orders/{orderId}` | Get a BackIssueOrder | PublishingDirector, CirculationManager, FulfillmentManager |
| GET | `/back-issue-orders/{orderId}` | Get a BackIssueOrder (flat detail) | PublishingDirector, CirculationManager, FulfillmentManager |
| POST | `/publications/{publicationId}/back-issue-orders/{orderId}/fulfill` | Fulfill an order (PENDING → FULFILLED) | FulfillmentManager |
| POST | `/publications/{publicationId}/back-issue-orders/{orderId}/ship` | Ship an order (FULFILLED → SHIPPED) | FulfillmentManager |
| POST | `/publications/{publicationId}/back-issue-orders/{orderId}/deliver` | Deliver an order (SHIPPED → DELIVERED); recognizes revenue | FulfillmentManager |
| POST | `/publications/{publicationId}/back-issue-orders/{orderId}/cancel` | Cancel an order (PENDING → CANCELLED) | CirculationManager |
| POST | `/publications/{publicationId}/back-issue-orders/{orderId}/refund` | Refund a delivered order (DELIVERED → REFUNDED) | CirculationManager |
| GET | `/publications/{publicationId}/subscriptions/{subscriptionId}/entitlements` | List DigitalEntitlements for a Subscription | PublishingDirector, CirculationManager |
| GET | `/publications/{publicationId}/subscriptions/{subscriptionId}/entitlements/{entitlementId}` | Get a DigitalEntitlement | PublishingDirector, CirculationManager |
| POST | `/publications/{publicationId}/subscriptions/{subscriptionId}/entitlements/{entitlementId}/revoke` | Manually revoke a DigitalEntitlement | CirculationManager |
| GET | `/digital-entitlements/{entitlementId}` | Get a DigitalEntitlement (flat detail) | PublishingDirector, CirculationManager |
| POST | `/publications/{publicationId}/circulation-audits` | Create a CirculationAuditRecord in DRAFT | CirculationManager |
| GET | `/publications/{publicationId}/circulation-audits` | List CirculationAuditRecords for a Publication | PublishingDirector, CirculationManager |
| GET | `/publications/{publicationId}/circulation-audits/{auditId}` | Get a CirculationAuditRecord | PublishingDirector, CirculationManager |
| POST | `/publications/{publicationId}/circulation-audits/{auditId}/file` | File the audit (DRAFT → FILED); computes distributions | CirculationManager |
| POST | `/publications/{publicationId}/circulation-audits/{auditId}/pass` | Mark the audit passed (FILED → AUDIT_PASSED) | PublishingDirector |
| POST | `/publications/{publicationId}/circulation-audits/{auditId}/fail` | Mark the audit failed (FILED → AUDIT_FAILED); may suspend the Publication | PublishingDirector |
| GET | `/circulation-audits/{auditId}` | Get a CirculationAuditRecord (flat detail) | PublishingDirector, CirculationManager |
| GET | `/deferred-revenue-entries/{entryId}` | Get a DeferredRevenueEntry (flat detail) | PublishingDirector, CirculationManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_PUBLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_ISSUE_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIBER_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_NOT_FOUND` | 404 Not Found |
| `ERR_RENEWAL_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_SERIES_NOT_FOUND` | 404 Not Found |
| `ERR_DONOR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PUBLICATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_ISSUE_NOT_AT_PRINTER` | 409 Conflict |
| `ERR_ISSUE_NOT_FINALIZED` | 409 Conflict |
| `ERR_ISSUE_PIPELINE_ACTIVE` | 409 Conflict |
| `ERR_ACTIVE_SUBSCRIPTIONS_REMAIN` | 409 Conflict |
| `ERR_LABELS_ALREADY_GENERATED` | 409 Conflict |
| `ERR_BATCH_ALREADY_GENERATED` | 409 Conflict |
| `ERR_BATCH_NOT_CONFIRMED` | 409 Conflict |
| `ERR_AD_CLOSE_LOCKED` | 409 Conflict |
| `ERR_AUDIT_NOT_QUALIFIED` | 409 Conflict |
| `ERR_AUDIT_NOT_FAILED` | 409 Conflict |
| `ERR_STALE_SUBSCRIPTION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ISSUE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_BATCH_VERSION` | 412 Precondition Failed |
| `ERR_EDITORIAL_NOT_CLOSED_YET` | 409 Conflict |
| `ERR_AD_CLOSE_NOT_REACHED` | 409 Conflict |
| `ERR_PRINTER_DATE_NOT_REACHED` | 409 Conflict |
| `ERR_MAIL_DATE_NOT_REACHED` | 409 Conflict |
| `ERR_TENDER_TOO_EARLY` | 409 Conflict |
| `ERR_RENEWAL_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_INVALID_START_ISSUE` | 422 Unprocessable Entity |
| `ERR_PAID_REQUIRES_PAYMENT` | 422 Unprocessable Entity |
| `ERR_CONTROLLED_MUST_BE_FREE` | 422 Unprocessable Entity |
| `ERR_UNDELIVERABLE_ADDRESS` | 422 Unprocessable Entity |
| `ERR_PAID_RATIO_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_AD_CONTENT_EXCEEDS_LIMIT` | 422 Unprocessable Entity |
| `ERR_STANDARD_NO_CONTROLLED` | 422 Unprocessable Entity |
| `ERR_NO_AD_PAGES` | 422 Unprocessable Entity |
| `ERR_PRINT_RUN_TOO_SMALL` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_INVENTORY` | 422 Unprocessable Entity |
| `ERR_UNRECOGNIZED_DEFERRED_REVENUE` | 409 Conflict |
| `ERR_INVALID_AUDIT_PERIOD` | 422 Unprocessable Entity |
| `ERR_DRAFT_AUDIT_EXISTS` | 422 Unprocessable Entity |
| `ERR_UNFILED_ISSUES_IN_PERIOD` | 422 Unprocessable Entity |
| `ERR_INVALID_PAGINATION_PARAMETERS` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
