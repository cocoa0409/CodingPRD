# Export Control Compliance API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Export Control & Sanctions Compliance API, the system of record for a corporate trade compliance office. The platform governs the full regulatory lifecycle of controlled products and technology: jurisdiction and classification determination (ECCN/USML), license requirement analysis keyed on destination, end user, and end use, restricted-party screening at order and shipment time, deemed-export access control for foreign nationals, license application and condition tracking, technology control plans with data segregation, violation intake with voluntary self-disclosure, and the long-retention audit recordkeeping that regulators expect to inspect years after the fact.

The design is driven by two non-negotiable properties. First, **segregation of duties**: the person who drafts a classification, applies for a license, requests an access grant, or identifies a violation can never be the person who approves, adjudicates, or closes it. Second, **immediate consistency**: when a screening match is confirmed, a license is revoked, or a list entry is activated, every downstream order, shipment, and grant that depends on the changed fact is reconciled in the same instant — there is no eventual-consistency window in which a held party's goods could keep moving. The API is mounted under the `/compliance` prefix and is consumed by compliance analysts, compliance managers, trade operations specialists, and the compliance director, each with deliberately non-overlapping write powers.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly four roles, spelled precisely as follows: `ComplianceAnalyst`, `ComplianceManager`, `TradeOpsSpecialist`, and `ComplianceDirector`.

A request missing either header, or presenting an `X-User-Role` value outside the four declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted to call the target endpoint per the authorization matrix in §4 is rejected with `ERR_FORBIDDEN` (HTTP 403).

For all four roles — `ComplianceAnalyst`, `ComplianceManager`, `TradeOpsSpecialist`, and `ComplianceDirector` — `X-User-ID` is an **opaque operator identifier** not tied to any persisted entity. The server records it where a workflow anchors accountability (for example as `submitted_by_user_id` on a `Classification`, `applicant_user_id` on a `License`, `requested_by_user_id` on an `AccessGrant`, or `identified_by_user_id` on a `Violation`) and compares those anchors against `X-User-ID` when enforcing segregation of duties, but it never treats `X-User-ID` as the `id` of any stored resource.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — `Product`, `Classification`, `Party`, `ScreeningListEntry`, `ScreeningResult`, `ExportOrder`, `License`, `Shipment`, `TechnologyControlPlan`, `AccessGrant`, and `Violation` — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that starts at creation and increments by exactly 1 on every mutation of the resource, including mutations driven by cascading side effects originating on another resource.

The `AuditRecord` resource is the single exception: it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from `AuditRecord`, because audit records are immutable once written and are removed only by the retention purge.

### 2.5. The Logical Clock and Scheduled Sweeps

The system evaluates every date- and time-sensitive rule against a **logical clock**, never against wall-clock time. Before any client sets it, the logical clock starts at exactly `2026-08-01T00:00:00Z` at server startup, and it never falls back to wall-clock time thereafter. An operator-facing capability — available to all four roles — advances the logical clock to a supplied `to_iso8601` instant (ISO 8601) and answers with the resulting `current_utc` value. "Current date" in this document means the calendar date (YYYY-MM-DD) of the logical clock at the moment the rule is evaluated.

Advancing the clock triggers two automatic expiry sweeps. Every `License` in `APPROVED` status whose `valid_until` date falls strictly before the current date transitions to `EXPIRED`. Every `AccessGrant` in `ACTIVE` status whose `end_date` is on or before the current date transitions to `EXPIRED`, and the affected `Party.active_grant_count` is decremented by 1 for each expired grant. Note the asymmetry between the two comparisons, which is deliberate: a license expires only once the current date has passed its last valid day, whereas a grant lapses the moment the current date reaches its exclusive end date.

### 2.6. Numeric Precision and Rounding

All monetary amounts are integer cents — no fractional cents exist anywhere in the system. Wherever a calculation produces a fractional cent result (the order surcharge and the per-shipment compliance fee), the value is rounded to a whole cent using **round half up**. Screening match scores are the one non-integer numeric quantity: they are computed and stored at exactly 2 decimal places, likewise with round half up. Percentage comparisons in the de minimis analysis are exact integer comparisons with no rounding at all. Datetime comparisons (retention, expiry sweeps, window checks) operate at second precision.

### 2.7. Optimistic Concurrency Control

Exactly one write endpoint in the system is guarded by optimistic concurrency control: the creation of a draft `Classification`. Such a request must carry `expected_product_version`, a non-optional input field holding the `version` of the parent `Product` as the client last observed it. If another writer has advanced the product's version since that observation — for example because another classification activated and repointed the product's `active_classification_id` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), and no draft is persisted. A classification draft is prepared against the product's current posture; refusing the write when that posture has changed prevents the drafter from silently classifying a product they have not actually seen. No other endpoint accepts a version field; all other conflict handling is expressed through state preconditions.

### 2.8. Validation Pipeline and Priority Ordering

When multiple rules could reject the same request, the server evaluates them in a fixed priority order and surfaces the first failure. The order is:

1. **Authentication** — presence of the two identity headers and membership of the role in the declared set (`ERR_UNAUTHENTICATED`, 401). Applies to every endpoint.
2. **Authorization** — the role is permitted to call this endpoint (`ERR_FORBIDDEN`, 403). Applies to every endpoint.
3. **Existence** — path-templated resource ids exist, validated strictly left to right, and body-supplied foreign-key references (`product_id`, `party_id`, `tcp_id`, `license_id`, `order_id`) exist (`ERR_NOT_FOUND`, 404). Applies to every resource endpoint.
4. **Request shape** — required fields present; no unknown, computed, or system-managed fields smuggled into the body; types valid; enum membership valid; dates in `YYYY-MM-DD` format; `quantity` greater than 0; `unit_value_cents` greater than 0; `approved_value_cents` greater than 0; `approved_quantity` greater than 0; `controlled_content_pct` at least 0 and at most 100; `valid_from` not after `valid_until`; `effective_from` not after `effective_to`; `start_date` strictly before `end_date`; every `conditions` entry within the declared condition set (`ERR_VALIDATION`, 400). Applies to every endpoint with a request body.
5. **Optimistic concurrency** — `expected_product_version` matches the product's current `version` (`ERR_STALE_VERSION`, 412). Applies only to classification creation.
6. **State preconditions** — the target entity is in a valid from-state for the requested transition, including the attached-license `APPROVED` checks on order release and shipment release (`ERR_INVALID_STATE`, 409). Applies to all state-transition endpoints.
7. **Sanctions safety** — destination embargo at order creation (`ERR_DESTINATION_EMBARGOED`); blocked or unresolved-match party posture at order hold release, shipment release, access grant creation, and grant activation (`ERR_PARTY_BLOCKED`, `ERR_SCREENING_REVIEW_PENDING`); hold release of a prohibited order (`ERR_ORDER_PROHIBITED`); license end-use condition breach at shipment release (`ERR_LICENSE_CONDITION_VIOLATION`) — all 409.
8. **Structural compliance** — segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); enclave period overlap (`ERR_TCP_PERIOD_OVERLAP`); grant period overlap (`ERR_GRANT_PERIOD_OVERLAP`); grant activation window (`ERR_GRANT_WINDOW_INVALID`); classification prerequisite (`ERR_CLASSIFICATION_REQUIRED`); release of a license-requiring order without one (`ERR_LICENSE_REQUIRED`); license attachment when none is required (`ERR_LICENSE_NOT_REQUIRED`); grant activation under a non-active plan (`ERR_TCP_INACTIVE`) — all 409.
9. **Cross-entity referential consistency** — license-to-order product match (`ERR_LICENSE_PRODUCT_MISMATCH`); license validity window coverage (`ERR_LICENSE_WINDOW_INVALID`); foreign-national eligibility (`ERR_FOREIGN_NATIONAL_REQUIRED`) — all 409.
10. **Fiscal sufficiency** — license quantity and value headroom (`ERR_LICENSE_QUANTITY_INSUFFICIENT`, `ERR_LICENSE_VALUE_INSUFFICIENT`); order quantity budget for new shipments (`ERR_ORDER_QUANTITY_EXCEEDED`) — all 409.

The practical consequence of this ordering is that a caller learns about authentication before authorization, about a missing resource before a malformed body, about a stale version before a state conflict, and about a sanctions-safety block before a fiscal shortfall.

### 2.9. Identifier Resolution and Referential Validation

Whenever a request path contains a templated resource identifier, the server validates identifiers sequentially from left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not correspond to an existing resource. References supplied in the request body — the `product_id` of a classification, license, TCP, or order; the `party_id` of an order or access grant; the `license_id` of an attach request; the `order_id` of a new shipment; the `tcp_id` of an access grant — are validated for existence at the same pipeline stage. A violation's `source_id` is deliberately polymorphic: it names the id of the entity the violation was observed on, interpreted according to `source_type` (`ORDER`, `SHIPMENT`, `ACCESS_GRANT`, `SCREENING`, or `OTHER`), and the same existence discipline applies.

### 2.10. Segregation of Duties

Four workflows anchor an initiating user at one step and forbid that same user from performing the decisive later step: a classification's `submitted_by_user_id` cannot equal its reviewer's `X-User-ID`; a license application's `applicant_user_id` cannot equal its reviewer's `X-User-ID`; an access grant's `requested_by_user_id` cannot equal its reviewer's `X-User-ID`; and a violation's `identified_by_user_id` cannot equal the `X-User-ID` of the user who substantiates, dismisses, or closes it. Any breach is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Resubmission of a returned license application re-anchors `applicant_user_id` to the resubmitting user, so a returned application can legitimately change hands.

### 2.11. Audit Trail and Recordkeeping Retention

Eleven business events are deemed regulatorily significant and cause an `AuditRecord` to be written at the moment they occur, identified by `event_type`: `CLASSIFICATION_ACTIVATED`, `LICENSE_APPROVED`, `LICENSE_REVOKED`, `ORDER_RELEASED`, `SHIPMENT_RELEASED`, `SHIPMENT_RETURNED`, `GRANT_ACTIVATED`, `GRANT_REVOKED`, `SCREENING_CONFIRMED_MATCH`, `VSD_SUBMITTED`, and `VIOLATION_CLOSED`. Each record captures the subject's `entity_type` (for example `License`) and polymorphic `entity_id`, the acting user's `actor_role` and `actor_user_id`, and a human-readable `detail` summary.

Every audit record is retained for five years: its `retain_until` timestamp is its own `created_at` plus 1825 days. A director-invoked purge capability deletes exactly the records whose `retain_until` is strictly earlier than the current logical clock and answers with a `purged_count`. A record whose `retain_until` equals the current clock time is **retained** — the comparison is strict. Records may be browsed through a filtered, paginated listing supporting `entity_type`, `entity_id`, and `event_type` filters.

## 3. Business Logic & Workflows

### 3.1. Product Registration and the Classification Lifecycle

Everything begins with the product catalogue. A `ComplianceAnalyst` registers a product with its `sku`, `name`, the `controlled_content_pct` (the integer percentage of controlled-origin content, between 0 and 100 inclusive, that feeds the de minimis analysis), and its `unit_value_cents`, which must be greater than zero. A new product is born `UNCLASSIFIED` with `classification_count` zero and `active_classification_id` null.

To classify a product, an analyst drafts a `Classification` carrying the target `product_id`, the `jurisdiction` (`EAR` or `ITAR`), the `classification_code` (an ECCN such as `5A002`, the basket designation `EAR99`, or a USML category such as `XI`), and the `determination_basis` (`SELF_CLASSIFICATION`, `CCATS`, or `CJ_DETERMINATION`). This is the system's one OCC-guarded write: the payload must include `expected_product_version` as described in §2.7, and a mismatch is refused with `ERR_STALE_VERSION`. A successfully created draft is stamped `DRAFT`, receives a per-product monotone `sequence` equal to the product's `classification_count` after that count is incremented (so the first classification of a product bears sequence 1), and its creation increments the product's `version` by 1 while advancing `classification_count` by 1. The count is monotone and never decremented, even when determinations are rejected or superseded.

A draft moves through a review gate. Submission by an analyst transitions `DRAFT → SUBMITTED` and anchors `submitted_by_user_id` to the caller; attempting it from any other state is an `ERR_INVALID_STATE` rejection. Review is a `ComplianceManager` decision (`decision` of `APPROVE` or `REJECT`) against a `SUBMITTED` record, and the reviewer's `X-User-ID` must differ from `submitted_by_user_id` under §2.10's segregation rule, else `ERR_SEGREGATION_OF_DUTIES`.

Approval is the moment the system pivots. On `APPROVE`, the classification becomes `ACTIVE`, `reviewed_by_user_id` is anchored, and three cascades fire in one motion: any other classification of the same product currently `ACTIVE` is pushed to `SUPERSEDED`; the product's `active_classification_id` repoints to the newly active record, its `status` becomes `CLASSIFIED`, and its `version` increments by 1; and an audit record of type `CLASSIFICATION_ACTIVATED` is written against the classification. A product therefore moves `UNCLASSIFIED → CLASSIFIED` on its first activation and `CLASSIFIED → CLASSIFIED` (pointer repoint only) on each subsequent one — it never returns to `UNCLASSIFIED`, and superseded classifications never unset the pointer. On `REJECT` the classification becomes `REJECTED` with only the reviewer anchor written. Rejection is not the end: an analyst may send a `REJECTED` record back to `DRAFT` through the revision loop, edit, and resubmit. `SUPERSEDED` is the classification's only terminal state. Classifications may be browsed through a filtered listing by `product_id` and `status`.

### 3.2. Parties, Screening List Administration, and the Match-Scoring Engine

Parties — customers, consignees, end users, and foreign-national persons — are registered with a `legal_name`, an ISO 3166-1 alpha-3 `country_code`, a `city` of principal address, a `party_type` (`CUSTOMER`, `CONSIGNEE`, `END_USER`, or `FOREIGN_NATIONAL`), and an `is_foreign_national` flag that defaults to false and gates deemed-export access. Both analysts and trade operations specialists may register parties. A new party's `screening_posture` is `UNSCREENED` and its `active_grant_count` is zero; `last_screened_at` stays null until the first screening runs. The party listing supports filters on `screening_posture`, `country_code`, and `party_type`.

The restricted-party universe is administered exclusively by the `ComplianceDirector` as `ScreeningListEntry` records, each with a `list_source` (`SDN`, `DENIED_PERSONS`, `ENTITY_LIST`, or `EMBARGOED_COUNTRY`), a `match_name` text, an alpha-3 `country_code`, and a `severity` of `PROHIBITED` or `RESTRICTED`. Severity carries regulatory weight: a `PROHIBITED` entry cannot be licensed around, while a `RESTRICTED` entry drives review rather than outright refusal. For `EMBARGOED_COUNTRY` entries the `match_name` is informational only — embargo matching uses the country code alone. Entries are born `ACTIVE` the moment they are created, and a director may toggle an entry between `ACTIVE` and `INACTIVE` through a set-status action naming the target `to`; each direction requires the entry to currently sit in the opposite state, so activating an already-`ACTIVE` entry or deactivating an already-`INACTIVE` one is rejected with `ERR_INVALID_STATE`. Only the re-activation direction (and birth) triggers the re-screen sweep described in §3.3, while deactivation touches nothing downstream.

Screening scores a party against the candidate set of all `ACTIVE` list entries. For a party P and an entry E, three component signals are computed. The country signal is 1.00 when `P.country_code` equals `E.country_code` and 0.00 otherwise. The city signal compares the lowercased, trimmed `city` of the party against city text associated with the entry; because list entries in this system carry no city text, the city signal is defined as 1.00 whenever the country signal is 1.00 and 0.00 otherwise. The name signal depends on the algorithm variant — recorded on every result as `algorithm_variant` — and the variant is chosen by the screening's `trigger_context`: order-submission screening runs the `EXACT` variant, while shipment, manual, and list-change screening run the `FUZZY` variant. Under `EXACT`, the name signal is 1.00 when the normalized party `legal_name` exactly equals the normalized `match_name`, and 0.00 otherwise — near-miss names earn nothing. Under `FUZZY`, both strings are tokenized into lowercase alphanumeric token sequences (splitting on every non-alphanumeric character and dropping empty tokens); the name signal is the number of tokens common to both sets divided by the number of tokens in their union, rounded to 2 decimal places round half up, with 0.00 when the union is empty, and an exact normalized equality still yields 1.00.

A hard gate then applies: if the entry's severity is `PROHIBITED` and the country signal is below 1.00, the match score for that pair is 0.00 outright. Otherwise the score is the weighted sum — 0.60 times the name signal, plus 0.25 times the country signal, plus 0.15 times the city signal — rounded to 2 decimal places round half up. Each candidate is compared against its own `threshold_used`: 0.85 for `PROHIBITED` entries and 0.70 otherwise. The best entry is the one with the highest score; ties break toward `PROHIBITED` severity first and then toward the entry with the earliest `created_at`. When the best score reaches or exceeds its threshold, the screening produces a `POTENTIAL_MATCH` result recording `matched_entry_id`, the `score`, and the `threshold_used`; otherwise it produces a `CLEAR` result with `matched_entry_id` null, `score` 0.00, and `threshold_used` null.

Either role that can register a party may also run an on-demand screening against it, which creates a result with `trigger_context` `MANUAL` under the `FUZZY` variant and returns it as a newly created resource. Every screening run, whatever its context, recomputes the party's `screening_posture` and `last_screened_at` per §3.3.

### 3.3. Match Resolution, Party Posture, and List-Change Sweeps

A party's `screening_posture` is a pure function of its entire history of screening results, regardless of age: `BLOCKED` when any result stands at `CONFIRMED_MATCH`; otherwise `REVIEW_REQUIRED` when any result stands at `POTENTIAL_MATCH`; otherwise `CLEAR` when at least one result exists (whether `CLEAR` or `FALSE_POSITIVE`); otherwise `UNSCREENED` when the party has never been screened. The party's `last_screened_at` mirrors the `created_at` of its most recent result. Result listings support filtering by `party_id`, `matched_entry_id`, `status`, and `trigger_context`.

`POTENTIAL_MATCH` results sit in a queue owned by the `ComplianceManager`, who resolves each one with a `resolution` of `FALSE_POSITIVE` or `CONFIRMED_MATCH`. Resolution from any state other than `POTENTIAL_MATCH` is `ERR_INVALID_STATE`. Either outcome anchors `resolved_by_user_id` and recomputes the party's posture. A `FALSE_POSITIVE` simply relaxes the posture if no other open matches remain. A `CONFIRMED_MATCH` is far more consequential: the party's posture flips to `BLOCKED`, every one of the party's export orders currently `CLEARED` or `LICENSED` is cascaded to `HELD` with its prior status recorded in `pre_hold_status`, every shipment of those orders in `PLANNED` or `SCREENED` is cascaded to `HELD`, and an audit record of type `SCREENING_CONFIRMED_MATCH` is written. `CLEAR` results never transition; `FALSE_POSITIVE` and `CONFIRMED_MATCH` are terminal.

The same cascade fires when the ground shifts under previously cleared parties. When a list entry is born `ACTIVE` or is re-activated from `INACTIVE`, the server runs a re-screen sweep: for every party referenced by an export order currently `CLEARED` or `LICENSED` — processed in order of that party's earliest such order by `created_at` ascending, with ties broken by the party's own `created_at` ascending — the FUZZY match score is computed against the newly activated entry only. If the score reaches or exceeds the entry's threshold, a new result is created with `trigger_context` `LIST_CHANGE` in status `POTENTIAL_MATCH` and the party's posture is recomputed; below the threshold, no row is created at all. The sweep never creates `CONFIRMED_MATCH` results directly. As the affected parties' postures deteriorate to `REVIEW_REQUIRED` or `BLOCKED`, their `CLEARED` or `LICENSED` orders cascade to `HELD` (with `pre_hold_status` recorded) and those orders' shipments in `PLANNED` or `SCREENED` cascade to `HELD` as well.

### 3.4. Export Order Intake and License Determination

A `TradeOpsSpecialist` opens an export order by naming the `product_id`, the `party_id` of the end user, the `destination_country` as an alpha-3 code, the `end_use` (`CIVILIAN`, `MILITARY`, or `DUAL_USE`), and the `quantity`, which must be greater than zero. Two guards stand at the door. The product must already be `CLASSIFIED` — that is, have an active classification — because the determination analysis requires one; otherwise the create fails with `ERR_CLASSIFICATION_REQUIRED`. And when the destination country matches an `ACTIVE` `EMBARGOED_COUNTRY` list entry with severity `PROHIBITED`, the create is refused with `ERR_DESTINATION_EMBARGOED` before anything is persisted.

A created order lands in `DRAFT` with a battery of computed fields. Its `goods_value_cents` is the ordered `quantity` multiplied by the product's `unit_value_cents`. The compliance surcharge then applies a two-tier rate keyed **only** on `goods_value_cents`, never on the running total: 0.02 when the goods value is below 100000 cents, and 0.035 when it is 100000 cents or more — an order whose goods value lands exactly on the boundary takes the higher rate. The `surcharge_cents` is the goods value multiplied by the applicable tier rate, rounded to a whole cent round half up, and `total_value_cents` is the sum of `goods_value_cents` and `surcharge_cents`. The order's `accumulated_fees_cents` and `shipped_quantity` both start at zero, `license_id` and `pre_hold_status` are null, and `determination` and `determination_classification_sequence` remain null until submission.

Creation also runs the **provisional** variant of the license determination, stored in `provisional_determination`. Both variants evaluate the same six-step decision ladder against the product's `ACTIVE` classification and the party's posture at evaluation time; they differ only in when they run. The ladder, in strict order: (1) if the destination country matches an `ACTIVE` `EMBARGOED_COUNTRY` entry with severity `PROHIBITED`, the outcome is `PROHIBITED`; (2) else if the party's `screening_posture` is `BLOCKED`, `PROHIBITED`; (3) else if the classification's `jurisdiction` is `ITAR`, `LICENSE_REQUIRED`; (4) else if the order's `end_use` is `MILITARY`, `LICENSE_REQUIRED`; (5) else if the `classification_code` is `EAR99`, `NOT_REQUIRED`; (6) otherwise — an EAR product with a real ECCN — the de minimis rule applies: the threshold is 10 percent for destinations in the Group E set (`CUB`, `IRN`, `PRK`, `SYR`) and 25 percent for all other destinations, and the outcome is `LICENSE_REQUIRED` only when `controlled_content_pct` is strictly greater than the threshold. A controlled-content percentage exactly equal to the threshold is `NOT_REQUIRED`. The provisional variant is frozen against the classification active at creation; later classification changes never retroactively rewrite it, so the provisional and final outcomes can legitimately diverge. Order listings support filtering by `product_id`, `party_id`, `license_id`, and `status`.

### 3.5. License Applications, Approval, and the Consumption Ledger

When the determination says a license is needed, a `ComplianceAnalyst` drafts a license application with the covered `product_id`, the `issuing_authority` (`BIS`, `DDTC`, or `OFAC`), the authorized envelope as `approved_value_cents` and `approved_quantity` (both required to be greater than zero), the validity window `valid_from` through `valid_until` as inclusive `YYYY-MM-DD` dates with `valid_from` not after `valid_until`, and an optional `conditions` list drawn from `NO_REEXPORT`, `NO_MILITARY_END_USE`, and `QUARTERLY_REPORTING` (defaulting to empty). The application starts in `DRAFT` with `license_number` still null.

Submission — including resubmission from `RETURNED_FOR_INFO` — moves the application to `SUBMITTED` and anchors `applicant_user_id` to the submitting analyst; the first submission additionally requires the product to be `CLASSIFIED`, failing with `ERR_CLASSIFICATION_REQUIRED` otherwise. A `ComplianceManager` then reviews with a three-way `decision`. `APPROVE` requires the reviewer to differ from `applicant_user_id` (else `ERR_SEGREGATION_OF_DUTIES`) and performs a cluster of writes: the license becomes `APPROVED`, `reviewed_by_user_id` is anchored, a `license_number` is assigned from a system-wide monotone counter formatted as `LIC-` followed by six zero-padded digits beginning at `LIC-000001`, `remaining_value_cents` initializes to `approved_value_cents` and `remaining_quantity` to `approved_quantity`, and an audit record of type `LICENSE_APPROVED` is written. `DENY` lands the application in the terminal `DENIED` state; `RETURN` sends it to `RETURNED_FOR_INFO`, from which an analyst may resubmit — the resubmission re-anchors `applicant_user_id`, so the segregation check on the next review binds to whoever resubmitted. Both deny and return carry the same segregation precondition as approval. License listings filter by `product_id` and `status`.

Once approved, a license behaves as a consumption ledger with two invariants that hold at all times after approval: `approved_value_cents` always equals `remaining_value_cents` plus `consumed_value_cents`, and `approved_quantity` always equals `remaining_quantity` plus `consumed_quantity`. Shipment releases draw the remaining side down and push the consumed side up; returns restore them by exactly the same amounts. Two automatic transitions ride on that ledger. After any decrement, if either `remaining_quantity` or `remaining_value_cents` reaches zero, the license moves `APPROVED → EXHAUSTED`. Conversely, when a shipment return restores both remaining values above zero and the current date has not passed `valid_until`, an `EXHAUSTED` license reactivates to `APPROVED` on its own. Separately, the clock sweep of §2.5 moves `APPROVED` licenses whose window has closed to `EXPIRED`. `DENIED`, `EXPIRED`, `EXHAUSTED`, and `REVOKED` are terminal.

The `ComplianceDirector` alone may revoke an `APPROVED` license — attempted from any other state it is `ERR_INVALID_STATE`. Revocation is a hard stop with a deliberate blast radius: the license becomes `REVOKED`; every order whose `license_id` names this license and whose status is `LICENSED` cascades to `HELD` with `pre_hold_status` recorded as `LICENSED` (the license reference itself is retained on the order); every shipment of those orders in `PLANNED` or `SCREENED` cascades to `HELD`; and an audit record of type `LICENSE_REVOKED` is written.

### 3.6. Order Clearance, Holds, License Attachment, and Release

Submitting a draft order — a `TradeOpsSpecialist` action allowed only from `DRAFT` — is the workflow's pivotal transaction, and it performs four things atomically. First, it runs order-context screening against the order's party: a screening result with `trigger_context` `ORDER` under the `EXACT` variant is created, and the party's posture and `last_screened_at` are recomputed. Second, it re-runs the determination ladder of §3.4 in its **final** variant against the classification active at submit time, pinning both the resulting `determination` and the `determination_classification_sequence` — the `sequence` of the `ACTIVE` classification used — so the decision remains explainable even after that classification is later superseded. Third, it enforces the classification prerequisite: a product that is not `CLASSIFIED` at submit time fails with `ERR_CLASSIFICATION_REQUIRED`. Fourth, the order auto-continues out of its momentary `IN_REVIEW` state: when the screening outcome is `CLEAR` and the determination is not `PROHIBITED`, the order lands in `CLEARED`; when the outcome is `POTENTIAL_MATCH` or `CONFIRMED_MATCH`, or the determination is `PROHIBITED`, it lands in `HELD` with `pre_hold_status` left null, marking it as a review hold that will return to `CLEARED`.

A held order is unlocked by a `ComplianceManager` through hold release. The checks run in this order: the order must be `HELD` (else `ERR_INVALID_STATE`); the party's posture must be `CLEAR`, with `REVIEW_REQUIRED` rejected as `ERR_SCREENING_REVIEW_PENDING` and `BLOCKED` as `ERR_PARTY_BLOCKED`; the determination must not be `PROHIBITED` (else `ERR_ORDER_PROHIBITED`); and when the order's `pre_hold_status` is `LICENSED` — meaning it was auto-held after a license was attached — the attached license must still be `APPROVED` (else `ERR_INVALID_STATE`) and its window must still cover the current date (else `ERR_LICENSE_WINDOW_INVALID`). On success the order returns to its `pre_hold_status` when one was recorded, and to `CLEARED` otherwise; `pre_hold_status` is then cleared back to null.

For an order that cleared with determination `LICENSE_REQUIRED`, the specialist attaches a license by `license_id`. Attachment requires the order to be `CLEARED` (else `ERR_INVALID_STATE`), the determination to be exactly `LICENSE_REQUIRED` (else `ERR_LICENSE_NOT_REQUIRED`), the referenced license to exist (else `ERR_NOT_FOUND`) and to stand `APPROVED` (else `ERR_INVALID_STATE`), the license's `product_id` to equal the order's `product_id` (else `ERR_LICENSE_PRODUCT_MISMATCH`), and the license window to cover the current date (else `ERR_LICENSE_WINDOW_INVALID`). Success records the `license_id` and moves the order `CLEARED → LICENSED`.

Release for fulfillment is a single action with two legal launch points. From `CLEARED`, the determination must be `NOT_REQUIRED`; a license-requiring order released without one fails with `ERR_LICENSE_REQUIRED`. From `LICENSED`, the attached license must still be `APPROVED` and still inside its validity window, failing with `ERR_INVALID_STATE` or `ERR_LICENSE_WINDOW_INVALID` respectively. Either path lands the order in `RELEASED` and writes an audit record of type `ORDER_RELEASED`.

Cancellation by the specialist is available from `DRAFT`, `IN_REVIEW`, `CLEARED`, and `HELD`, landing the order in the terminal `CANCELLED` state. Once `RELEASED`, an order no longer cancels: it closes automatically when every one of its shipments has reached a terminal state and the total quantity across `DELIVERED` shipments equals the order's `quantity`, transitioning `RELEASED → CLOSED`. `CLOSED` and `CANCELLED` are terminal.

### 3.7. Shipments: Planning, Screening, Release, and In-Transit Events

Shipments are the physical fulfillment of a released order. A specialist creates one by naming the parent `order_id`, the `quantity` in this shipment (greater than zero), and the `planned_ship_date`. The parent order must be `LICENSED` or `RELEASED` (else `ERR_INVALID_STATE`), and the quantity budget is enforced at creation: the sum of `quantity` across the order's shipments in `PLANNED`, `SCREENED`, `HELD`, `RELEASED`, `IN_TRANSIT`, or `DELIVERED` status, plus the new shipment's quantity, must not exceed the order's `quantity` — a breach is `ERR_ORDER_QUANTITY_EXCEEDED`. A created shipment starts `PLANNED` with `screening_result_id` null and `consumed_value_cents` and `fee_cents` both zero until release. Shipment listings filter by `order_id` and `status`.

Before a shipment can move, the end user is re-screened in shipment context. Screening from `PLANNED` — or re-screening from `HELD` after a review has resolved — runs the `FUZZY` variant against the parent order's party, records the new result's id in the shipment's `screening_result_id`, and recomputes the party's posture and `last_screened_at`. A `CLEAR` outcome lands the shipment in `SCREENED`; a `POTENTIAL_MATCH` or `CONFIRMED_MATCH` outcome lands it in `HELD` instead, awaiting the resolution workflow of §3.3. Any other from-state is `ERR_INVALID_STATE`.

Release is the fiscally decisive step, guarded by a layered check set: the shipment must be `SCREENED` (else `ERR_INVALID_STATE`); the parent order must be `RELEASED` (else `ERR_INVALID_STATE`); the party's posture must be neither `BLOCKED` (`ERR_PARTY_BLOCKED`) nor `REVIEW_REQUIRED` (`ERR_SCREENING_REVIEW_PENDING`); and when the order carries a `license_id`, the license must be `APPROVED` (else `ERR_INVALID_STATE`), its window must cover the current date (else `ERR_LICENSE_WINDOW_INVALID`), a license carrying the `NO_MILITARY_END_USE` condition forbids release of an order whose `end_use` is `MILITARY` (`ERR_LICENSE_CONDITION_VIOLATION`), the shipment's `quantity` must not exceed the license's `remaining_quantity` (`ERR_LICENSE_QUANTITY_INSUFFICIENT`), and the shipment's consumed value must not exceed the license's `remaining_value_cents` (`ERR_LICENSE_VALUE_INSUFFICIENT`). Both sufficiency comparisons are inclusive — a shipment exactly equal to the remaining quantity or value is allowed, and it is precisely that equality which exhausts the license.

On release the following happen together: the shipment's `consumed_value_cents` is set to its `quantity` multiplied by the product's `unit_value_cents` (an exact integer, no rounding); its `fee_cents` is computed as 1.5 percent of that consumed value — that is, the consumed value multiplied by 0.015 — rounded to a whole cent round half up; the license's `remaining_quantity` decreases by the quantity, `remaining_value_cents` decreases by the consumed value, `consumed_quantity` and `consumed_value_cents` increase by the same amounts, and the license's `version` increments by 1; the order's `accumulated_fees_cents` increases by this shipment's `fee_cents`, its `shipped_quantity` increases by the quantity, and its `version` increments by 1; if either remaining balance has hit zero the license flips to `EXHAUSTED`; and an audit record of type `SHIPMENT_RELEASED` is written. The rounding order is contractual: each shipment's fee is computed and rounded individually at its own release moment and then accumulated; summing shipment values first and rounding once is forbidden because it yields different cents. Returns do not refund the fee — `accumulated_fees_cents` only ever grows.

After release, a shipment advances through event-driven transitions supplied as an `event`. `DEPART` moves `RELEASED → IN_TRANSIT`. `DELIVER` moves `IN_TRANSIT → DELIVERED` and runs the order's auto-close check of §3.6 (the shipped quantity was already counted at release and does not change here). `RETURN` moves `IN_TRANSIT → RETURNED` and unwinds the ledger: when the order carries a license, its `remaining_quantity` and `remaining_value_cents` are restored by the shipment's quantity and consumed value, `consumed_quantity` and `consumed_value_cents` decrease by the same amounts, and the license's `version` increments by 1; the order's `shipped_quantity` decreases by the quantity and its `version` increments by 1; if the license was `EXHAUSTED` and the restoration leaves both remaining values above zero while the current date is still within `valid_until`, the license reactivates to `APPROVED`; and an audit record of type `SHIPMENT_RETURNED` is written. `CANCEL` from `PLANNED`, `SCREENED`, or `HELD` lands the shipment in `CANCELLED`. `DELIVERED`, `RETURNED`, and `CANCELLED` are terminal. Independently of operator action, the cascades of §3.3 and §3.5 can push a shipment `PLANNED → HELD` or `SCREENED → HELD` whenever its parent order is auto-held by license revocation or a party posture change.

### 3.8. Technology Control Plans and Foreign-National Access Grants

Deemed-export control is organized around the technology control plan. An analyst creates a plan with a `name`, the `enclave_id` identifying the segregated data enclave or lab zone it governs, the `product_id` of the controlled technology covered, a `segregation_level` of `LEVEL_1`, `LEVEL_2`, or `LEVEL_3`, and a closed effective window `effective_from` through `effective_to` with the start not after the end. A plan begins in `DRAFT`. Plan listings filter by `product_id`, `status`, and `enclave_id`.

Plan status changes are driven by the analyst through a single set-status capability taking a target `to`. Activation (`to` `ACTIVE`) is allowed from `DRAFT` or `SUSPENDED` and carries two checks: no other plan on the same `enclave_id` may sit in `ACTIVE` or `SUSPENDED` with an effective window that overlaps under closed-interval semantics — a shared endpoint date counts as overlap — else `ERR_TCP_PERIOD_OVERLAP`; and activation from `DRAFT` additionally requires the covered product to be `CLASSIFIED`, else `ERR_CLASSIFICATION_REQUIRED`. Suspension (`to` `SUSPENDED`) is allowed only from `ACTIVE`. Termination (`to` `TERMINATED`) is allowed from `DRAFT`, `ACTIVE`, or `SUSPENDED`, and it cascades to the plan's grants: every grant still `REQUESTED` is denied outright, and every grant in `APPROVED` or `ACTIVE` is revoked, with the party's `active_grant_count` decremented by 1 for each grant that was `ACTIVE`. Any out-of-state target is `ERR_INVALID_STATE`. `TERMINATED` is terminal; the suspend–reinstate cycle may repeat freely within the overlap constraint.

Access grants are how a foreign national is admitted to a plan. An analyst requests one by naming the `tcp_id`, the `party_id`, and a half-open access window from `start_date` (inclusive) to `end_date` (exclusive), with the start strictly before the end. Two eligibility checks gate creation: the party's `is_foreign_national` must be true (else `ERR_FOREIGN_NATIONAL_REQUIRED`), and the party's `screening_posture` must not be `BLOCKED` (else `ERR_PARTY_BLOCKED`). A created grant starts `REQUESTED` with `requested_by_user_id` anchored.

Review by a `ComplianceManager` requires the reviewer to differ from `requested_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`). A `decision` of `APPROVE` additionally enforces the no-double-access rule: no other grant with the same `party_id` and `tcp_id` may exist in `APPROVED` or `ACTIVE` status with a half-open-overlapping window, else `ERR_GRANT_PERIOD_OVERLAP`. A `decision` of `DENY` lands the grant in `DENIED`. Either outcome anchors `reviewed_by_user_id`.

Activation is a separate manager action with its own four-part gate: the grant must be `APPROVED` (else `ERR_INVALID_STATE`); the parent plan must be `ACTIVE` (else `ERR_TCP_INACTIVE`); the current date must fall inside the half-open window — on or after `start_date` and strictly before `end_date` — else `ERR_GRANT_WINDOW_INVALID`; and the party's posture must not be `BLOCKED` (else `ERR_PARTY_BLOCKED`). The overlap check runs again at activation with precise half-open semantics: two grants for the same party and plan conflict only when the first grant's `start_date` is strictly before the second's `end_date` **and** the second's `start_date` is strictly before the first's `end_date`; windows that merely touch — one's `end_date` equal to the other's `start_date` — do not conflict. Activation increments the party's `active_grant_count` by 1 and writes an audit record of type `GRANT_ACTIVATED`. A manager may revoke an `ACTIVE` grant, which decrements `active_grant_count` by 1 and writes `GRANT_REVOKED`. Finally, the clock sweep of §2.5 expires `ACTIVE` grants whose `end_date` has been reached, decrementing the count per expired grant. `DENIED`, `REVOKED`, and `EXPIRED` are terminal. Grant listings filter by `tcp_id`, `party_id`, and `status`.

### 3.9. Violations, Voluntary Self-Disclosure, and Audit Recordkeeping

When something has gone wrong — a screening miss, an unauthorized shipment, a broken plan control — any of the three operational roles (analyst, manager, or specialist) may identify a potential violation, supplying the `source_type` (`ORDER`, `SHIPMENT`, `ACCESS_GRANT`, `SCREENING`, or `OTHER`), the polymorphic `source_id` it refers to, a `severity` of `MINOR`, `MATERIAL`, or `CRITICAL`, and a free-text `description`. The record opens as `IDENTIFIED` with `identified_by_user_id` anchored to the caller and `disclosure_reference` still null.

A `ComplianceManager` then advances the case through event-driven transitions supplied as an `event`. `START_REVIEW` moves `IDENTIFIED → UNDER_REVIEW`. From `UNDER_REVIEW`, `SUBSTANTIATE` lands the case at `SUBSTANTIATED` and `DISMISS` lands it at `UNFOUNDED`; both adjudication events require the actor's `X-User-ID` to differ from `identified_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`) and anchor `adjudicated_by_user_id`. Every event attempted from a wrong from-state is `ERR_INVALID_STATE`.

Only a substantiated violation can be disclosed to the regulator, and only the `ComplianceDirector` may file it. Submission moves `SUBSTANTIATED → DISCLOSED`, assigns a `disclosure_reference` from a system-wide monotone counter formatted as `VSD-` followed by six zero-padded digits beginning at `VSD-000001`, and writes an audit record of type `VSD_SUBMITTED`. Closure is a manager action via the `CLOSE` event from either `DISCLOSED` or `UNFOUNDED`, again segregated from `identified_by_user_id`, and it writes `VIOLATION_CLOSED`. `CLOSED` is terminal.

The audit trail these workflows produce is queryable by every role through the recordkeeping listing described in §2.11, and the director's purge enforces the five-year retention boundary exactly as specified there: strictly-past `retain_until` records are deleted and counted in `purged_count`; a record whose retention instant equals the current clock survives.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or act upon an existing resource return `200 OK`. Note that the two screening actions (manual party screening and shipment screening) return `201` because each creates a new `ScreeningResult` resource, even though they are phrased as actions on an existing resource.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/compliance/products` | Create a product | ComplianceAnalyst |
| GET | `/compliance/products/{id}` | Get a product | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| POST | `/compliance/classifications` | Create a draft classification (OCC-guarded on the product's version) | ComplianceAnalyst |
| GET | `/compliance/classifications/{id}` | Get a classification | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| GET | `/compliance/classifications` | List classifications, filterable by product and status | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| POST | `/compliance/classifications/{id}/submit` | Submit a draft classification for review | ComplianceAnalyst |
| POST | `/compliance/classifications/{id}/review` | Approve or reject a submitted classification | ComplianceManager |
| POST | `/compliance/classifications/{id}/revise` | Return a rejected classification to draft | ComplianceAnalyst |
| POST | `/compliance/parties` | Create a party | ComplianceAnalyst, TradeOpsSpecialist |
| GET | `/compliance/parties/{id}` | Get a party | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| GET | `/compliance/parties` | List parties with filters and pagination | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| POST | `/compliance/parties/{id}/screen` | Run a manual restricted-party screening (FUZZY variant) | ComplianceAnalyst, TradeOpsSpecialist |
| POST | `/compliance/screening-list-entries` | Create a screening list entry (born ACTIVE; runs the re-screen sweep) | ComplianceDirector |
| POST | `/compliance/screening-list-entries/{id}/set-status` | Activate or deactivate a list entry; activation runs the LIST_CHANGE sweep | ComplianceDirector |
| GET | `/compliance/screening-results/{id}` | Get a screening result | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| GET | `/compliance/screening-results` | List screening results with filters and pagination | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| POST | `/compliance/screening-results/{id}/resolve` | Resolve a POTENTIAL_MATCH as FALSE_POSITIVE or CONFIRMED_MATCH | ComplianceManager |
| POST | `/compliance/orders` | Create an export order (provisional determination computed) | TradeOpsSpecialist |
| GET | `/compliance/orders/{id}` | Get an order | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| GET | `/compliance/orders` | List orders with filters and pagination | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| POST | `/compliance/orders/{id}/submit` | Submit an order: ORDER-context screening plus final determination | TradeOpsSpecialist |
| POST | `/compliance/orders/{id}/release-hold` | Release a HELD order back to its pre-hold status | ComplianceManager |
| POST | `/compliance/orders/{id}/attach-license` | Attach an APPROVED license to a CLEARED LICENSE_REQUIRED order | TradeOpsSpecialist |
| POST | `/compliance/orders/{id}/release` | Release a CLEARED (NOT_REQUIRED) or LICENSED order for fulfillment | TradeOpsSpecialist |
| POST | `/compliance/orders/{id}/cancel` | Cancel an order from DRAFT, IN_REVIEW, CLEARED, or HELD | TradeOpsSpecialist |
| POST | `/compliance/licenses` | Create a draft license application | ComplianceAnalyst |
| GET | `/compliance/licenses/{id}` | Get a license | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| GET | `/compliance/licenses` | List licenses with filters and pagination | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| POST | `/compliance/licenses/{id}/submit` | Submit or resubmit a license application | ComplianceAnalyst |
| POST | `/compliance/licenses/{id}/review` | Approve, deny, or return a submitted license application | ComplianceManager |
| POST | `/compliance/licenses/{id}/revoke` | Revoke an APPROVED license (cascades to orders and shipments) | ComplianceDirector |
| POST | `/compliance/shipments` | Create a shipment under a LICENSED or RELEASED order | TradeOpsSpecialist |
| GET | `/compliance/shipments/{id}` | Get a shipment | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| GET | `/compliance/shipments` | List shipments with filters and pagination | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| POST | `/compliance/shipments/{id}/screen` | Run SHIPMENT-context screening (FUZZY) on the order's party | TradeOpsSpecialist |
| POST | `/compliance/shipments/{id}/release` | Release a SCREENED shipment; consumes license value and quantity | TradeOpsSpecialist |
| POST | `/compliance/shipments/{id}/advance` | Advance a shipment: DEPART, DELIVER, RETURN, or CANCEL | TradeOpsSpecialist |
| POST | `/compliance/tcps` | Create a technology control plan | ComplianceAnalyst |
| GET | `/compliance/tcps/{id}` | Get a technology control plan | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| GET | `/compliance/tcps` | List technology control plans with filters and pagination | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| POST | `/compliance/tcps/{id}/set-status` | Transition a plan: ACTIVE, SUSPENDED, or TERMINATED | ComplianceAnalyst |
| POST | `/compliance/access-grants` | Request a foreign-national access grant under a plan | ComplianceAnalyst |
| GET | `/compliance/access-grants/{id}` | Get an access grant | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| GET | `/compliance/access-grants` | List access grants with filters and pagination | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| POST | `/compliance/access-grants/{id}/review` | Approve or deny a requested access grant | ComplianceManager |
| POST | `/compliance/access-grants/{id}/activate` | Activate an APPROVED grant (window, plan-active, posture, overlap checks) | ComplianceManager |
| POST | `/compliance/access-grants/{id}/revoke` | Revoke an ACTIVE grant | ComplianceManager |
| POST | `/compliance/violations` | Identify a potential violation | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist |
| GET | `/compliance/violations/{id}` | Get a violation | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| POST | `/compliance/violations/{id}/advance` | Advance a violation: START_REVIEW, SUBSTANTIATE, DISMISS, or CLOSE | ComplianceManager |
| POST | `/compliance/violations/{id}/submit-disclosure` | Submit a voluntary self-disclosure for a SUBSTANTIATED violation | ComplianceDirector |
| GET | `/compliance/audit-records` | List audit records with filters and pagination | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |
| POST | `/compliance/audit-records/purge` | Purge audit records whose retention deadline is strictly past | ComplianceDirector |
| POST | `/compliance/_clock/set_current_utc` | Set the logical clock (ISO 8601) and run the expiry sweeps | ComplianceAnalyst, ComplianceManager, TradeOpsSpecialist, ComplianceDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DESTINATION_EMBARGOED` | 409 |
| `ERR_PARTY_BLOCKED` | 409 |
| `ERR_SCREENING_REVIEW_PENDING` | 409 |
| `ERR_ORDER_PROHIBITED` | 409 |
| `ERR_LICENSE_CONDITION_VIOLATION` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_TCP_PERIOD_OVERLAP` | 409 |
| `ERR_GRANT_PERIOD_OVERLAP` | 409 |
| `ERR_GRANT_WINDOW_INVALID` | 409 |
| `ERR_CLASSIFICATION_REQUIRED` | 409 |
| `ERR_LICENSE_REQUIRED` | 409 |
| `ERR_LICENSE_NOT_REQUIRED` | 409 |
| `ERR_TCP_INACTIVE` | 409 |
| `ERR_LICENSE_PRODUCT_MISMATCH` | 409 |
| `ERR_LICENSE_WINDOW_INVALID` | 409 |
| `ERR_FOREIGN_NATIONAL_REQUIRED` | 409 |
| `ERR_LICENSE_QUANTITY_INSUFFICIENT` | 409 |
| `ERR_LICENSE_VALUE_INSUFFICIENT` | 409 |
| `ERR_ORDER_QUANTITY_EXCEEDED` | 409 |
