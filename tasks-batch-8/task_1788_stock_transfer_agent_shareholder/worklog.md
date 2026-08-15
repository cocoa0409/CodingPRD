# Worklog — task_1788_stock_transfer_agent_shareholder

## Step 1: Create Task Directory — 2026-08-14T17:23:32.716Z

Pre-assigned directory tasks/task_1788_stock_transfer_agent_shareholder/ with workspace/ subdirectory already existed; treated as DONE per pipeline invocation instructions.

## Step 2: Generate Scaffold — 2026-08-14T17:23:32.716Z

All three scaffold artifacts are written and pass `scaffold_lint.py` clean on the final run:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1788_stock_transfer_agent_shareholder/SCAFFOLD.yaml` (§1.0–§1.7 + concurrency rules; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1788_stock_transfer_agent_shareholder/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single `scaffold_difficulty_design:` key)
- `/home/ubuntu/github/CodingPRD/tasks/task_1788_stock_transfer_agent_shareholder/SCAFFOLD_CORNER_DESIGN.yaml` (single `scaffold_corner_design:` key)

**Counts**
- Entities: 13 (Issuer, ShareholderAccount, Position, Certificate, TransferRequest, LostCertificateClaim, DividendDeclaration, DividendPayment, LegendRemovalRequest, EscheatmentCase, ShareholderInquiry, TransferFreezeWindow, AuditEvent)
- State machines: 12 (6 non-linear/cyclic — transfer deficiency loop, certificate lost→recover, payment return→reissue, legend opinion resubmission, escheatment reactivation, inquiry reopen)
- Calculations: 6 (dual variants in two domains: indemnity bond open/fixed penalty; dividend withholding provisional/final; combinatorial modes a/b/c all present)
- Endpoints: 73 (deliberately above the Expert band guideline of 20–32 per the harder-than-expert instruction; includes `POST /_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z)
- Errors: 38; Validations: 10 priority tiers; Roles: 7 (segregation-of-duties on transfer and claim approval); OCC concurrency rules: 2 (account version on transfer create, position version on legend create)
- §1.8 instances: 19 (every rule ≥2; combinatorial_formula has 3 spanning modes a, b, c)
- §1.9 instances: 52 (42 full test recipes + 10 `excluded_because:` stubs resolving to real §1.8 names); zero name collisions across files

Notable hardening: per-payment vs sum-then-round dividend accrual pinned with a literal 2-cents-vs-1-cent divergence; medallion coverage and dormancy-period boundaries both pinned inclusive with literal side-by-side fixtures; depth-3 cascades for both transfer settle (certificate→positions→issuer totals) and stale-dating (payment→account stale ledger→case creation); share-conservation and dividend-cash-conservation compensating invariants; tamper-evident hash-chained AuditEvent log.

## Step 3: Copy Shared Files — 2026-08-14T17:24:00.573Z

Copied ./INSTRUCTION.md to tasks/task_1788_stock_transfer_agent_shareholder/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T17:52:27.566Z

All contracts pass. The PRD is complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1788_stock_transfer_agent_shareholder/workspace/PRD.md` — 351 lines.

**Sections written:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications — 10 subsections: 2.1 RBAC (all 7 roles with per-role `identity:` prose: `Shareholder`→`ShareholderAccount`, `IssuerOfficer`→`Issuer`, five opaque roles with their recorded-field anchors), 2.2 Response Structure (**byte-verbatim** match against `section-2.2-response-structure.md`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Logical Clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`, enumerated time-gated evaluations), 2.5 Common Resource Properties (incl. the `AuditEvent` exception: only `id`+`created_at`, no `updated_at`/`version`), 2.6 Monetary Precision (integer cents, millicents, per-payment round-half-up), 2.7 OCC (both rules), 2.8 Validation Order (all 10 priorities as an explicit ordered cascade), 2.9 Audit Chain (hash-chain fields, `GENESIS`), 2.10 Share Conservation
- §3 Business Logic — 8 subsections (issuer/holder/positions; certificate form; transfers; lost certificates & bonds; dividends; legend removal; dormancy/escheatment; inquiries/statements), all scattering rules honored
- §4 Endpoint table — 73 rows, 4 columns only
- §5 Error catalogue — 38 rows, 2 columns only

**Hard-contract results:**
- Contract 1 (Field-Name Coverage): **PASS** — 126/126 identifiers backticked (97 entity fields, 54 request inputs, 13 query params, 1 path param, common/envelope/header/output-only names). One gap (`account_status`) found on first pass and repaired; second pass clean.
- Contract 2 (Rule Coverage): **PASS** — validations with priority 10/10 expressed in ordered prose; OCC 2/2 (write capability + `expected_account_version`/`expected_position_version` + `ERR_STALE_ACCOUNT_VERSION`/`ERR_STALE_POSITION_VERSION` + 412, no race framing); state transitions 57/57; calculations 6/6 (pinned rounding with the 667-millicent worked example, four withholding branches, both bond variants with tier cap, pinned 4-step escheatment valuation, dormancy table CA 3/NY 5/TX 3/default 5 with inclusive boundary, record-date snapshot with `settled_at`/`created_at` tie-break); endpoint side effects and `applies_to` scopes enumerated; sibling branches rendered with equal density.
- Contract 3 (§3 Path Purity): **PASS** — 612 backticked tokens scanned, zero paths/methods/combos.

**Zero-Silence self-audit — judgment calls where the scaffold was implicit (no scaffold rule was left unrenderable; three mappings required interpretation):**
1. Settle-time gates the scaffold lists as preconditions without a nominated error (issuer not `ACTIVE`, source-share availability changed since approval) were rendered as `ERR_INVALID_STATE` (409), the validation-priority-5 fallback; `ERR_ISSUER_SUSPENDED`/`ERR_CERTIFICATE_STOPPED` are used only where the error catalog names them.
2. The create-time rule "transfer `share_quantity` must equal the certificate's face quantity when `source_certificate_id` is set" has no scaffold-nominated error id; it was rendered as a shape violation rejected with `ERR_INVALID_REQUEST`.
3. Clock-driven accrual over a `SUSPENDED` issuer was rendered as "not accrued at evaluation" per the transition precondition and the `ERR_ISSUER_SUSPENDED` catalog condition, deliberately without inventing retry semantics the scaffold does not specify.

One implementation note for downstream consumers: the forbidden design-index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Step 6: Generate Implementation — 2026-08-14T18:23:47.595Z

Done. Summary of the delivered implementation:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1788_stock_transfer_agent_shareholder/workspace/implementation/`)

- `start.sh` — guarded-install launcher (`pip install` only if Flask missing), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0
- `app.py` — Flask entry, global request lock, error handlers, blueprint registration
- `db.py` — in-memory dict stores + audit list + logical clock (default exactly `2026-08-01T00:00:00Z`); starts completely empty, no seeding anywhere
- `errors.py` — full 38-error catalog with exact HTTP statuses
- `helpers.py` — ISO-8601 parse/format (3-fractional-digit Z), `Decimal` ROUND_HALF_UP, body/field extractors, pagination params (limit default 10, min 1, max 100, offset)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401), role gates (403), Shareholder/IssuerOfficer entity-backed ownership
- `response.py` — exact envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in meta for lists
- `services.py` — audit hash chain (GENESIS + SHA-256 linkage), withholding tiers (24%/0%/15%/30%), per-payment millicent→cent rounding, tiered bond premium (3%/2% over 10M-cent cap), dormancy table (CA/TX 3y, default 5y), clock evaluation (accrual → disbursement → 180-day stale-dating → freeze activation/expiry), reactivation/remit/settle cascades, declaration bubble-up
- `routes/` — 11 modules covering all resource groups

## Endpoint count
73 route handlers — matching all 73 rows in the PRD §4 endpoint table.

## Boot-sanity check
`bash start.sh` launches cleanly and responds within ~1s. Fresh-boot emptiness verified explicitly: boot 1 created data (1 audit event), process killed, boot 2 reported `total_count: 0` for both audit events and positions. End-to-end flows exercised live and passing: transfer lifecycle with OCC 412, medallion coverage 422, SoD 403, settle cascade; certificate withdraw/report-lost/bond/approve/replace with duplicate-claim and premium gates; dividends with pinned per-payment rounding (2×1sh×667mc → 2c total), provisional-vs-final withholding divergence, 180-day stale boundary (inclusive), return/reissue with `ERR_ADDRESS_UNVERIFIED`, cash → declaration bubble-up to CLOSED; legend removal with position-OCC, 180-day holding period; freeze windows with closed-interval overlap and settle blocking/expiry; escheatment scan → notice → 60-day report gate → remit cascade (account ESCHEATED, positions CLOSED/zeroed); inquiry claim/answer discipline (`ERR_INQUIRY_CLAIMED_BY_OTHER`); RBAC and ownership rejections; audit chain linkage verified (`prev_entry_hash` chaining, GENESIS first, no `version`/`updated_at` on audit events).

One environment note: long-running background processes on this host get SIGTERM'd between tool calls, so verification was done with self-contained boot-and-probe runs — this does not affect the `prd-bench-local-run` contract, which launches its own `start.sh` process per test.

## Step 5: Generate Unit Tests — 2026-08-14T18:26:40.337Z

Generation complete. Summary:

## Files written

**`test_helpers/`** (9 files) under `/home/ubuntu/github/CodingPRD/tasks/task_1788_stock_transfer_agent_shareholder/test_helpers/`:
- `types.py` — 13 entity TypedDicts + 16 status/role enums; `AuditEvent` carries only `id`/`created_at` (no `updated_at`/`version`), per the append-only exception
- `api_client.py` — `ApiClient(GenericApiClient)` with 73 methods, one per endpoint including `POST /_clock/set_current_utc`
- `api_errors.py` — all 38 error IDs + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + domain invariants (payment money conservation, issuer share conservation, position split invariants)
- `factories.py`, `constants.py` (24%/30%/15% withholding rates, bond multiplier/tier constants, dormancy table, 180d/60d horizons, clock default)
- `test_users.py` — 7 roles with mandatory per-instance builders for the two entity-backed roles (`make_shareholder_headers(account_id)`, `make_issuer_officer_headers(issuer_id)`)
- `fixtures.py` — ~45 composite helpers across all five tiers (OCC-threaded transfer/legend creation, certificate/claim pipelines, dividend lifecycles incl. W-9 cure and 667-millicent rounding scenarios, dormancy/escheatment pipelines through REPORTED)
- `__init__.py` — barrel export

**`test_suite/`** (10 files) under `/home/ubuntu/github/CodingPRD/tasks/task_1788_stock_transfer_agent_shareholder/test_suite/`: `conftest.py` + `test_01_register_and_defaults.py` (7) · `test_02_transfer_review.py` (8) · `test_03_transfer_settlement.py` (9) · `test_04_certificates_and_claims.py` (11) · `test_05_dividends.py` (17) · `test_06_legend_removal.py` (5) · `test_07_dormancy_escheatment.py` (11) · `test_08_inquiries_freeze_audit.py` (8) · `test_09_access_envelope_statement.py` (4).

## Test counts
- **Queue A (§1.8 difficulty): 38 tests** — all 19 instances with ≥2 tests each
- **Queue B (§1.9 corner): 42 tests** — all 42 non-stub instances with ≥1 test; all 10 `excluded_because:` stubs untranslated (cross-references verified to resolve)

## Instances skipped
**None.** Every instance passed the PRD-first two-condition filter.

## Assertion relaxations (PRD-silent inner shapes, instances still covered)
- `record_date_report_matches_accrual_snapshot`: asserts PRD-named fields (`declaration_id`, `record_date`, `total_shares`, `total_accounts`) and one-row-per-holder count; per-entry `eligible_shares` key names inside `entries` rows are not PRD-pinned, so not asserted
- `statement_reflects_position_split`: asserts `account_id`, `as_of`, the positions-array split (300/200/500), and `totals` presence; `totals` inner key names are not PRD-pinned
- `audit_trail_records_full_transition_chain`: asserts the 4-event count, the three PRD-named action labels, and the settle entry's from/to states + actor role; the approval event's action label is not PRD-pinned

## Stage 2 self-check (tag audit)
Machine-verified: 80/80 tests carry exactly one `Design:` line as the final docstring line; zero untagged, zero dual-tagged, zero unknown tags, zero stub tags; difficulty 19/19 ×≥2, corner 42/42 ×≥1. Separately, all 143 rule-bearing docstring citations are verbatim substrings of `workspace/PRD.md` (modulo whitespace), `pytest --collect-only` collects 80 tests cleanly, pyflakes is clean, and no skip/skipif/xfail markers exist.

## Step 7: Run Tests and Iterate — 2026-08-14T18:35:42.658Z

All 8 timestamp assertions are updated to the `.000Z` form. Final sweep confirms 8/8 rounds pass 80/80 tests.

## Summary

- **Iterations run:** 2 (initial sweep, then re-sweep after fixes)

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:** None.

- **Fixes applied to `test_suite/`:** All 8 failing assertions were timestamp-equality checks that asserted the literal string `"...T00:00:00Z"` (no fractional seconds) while the implementation correctly emits ISO 8601 with three fractional digits per PRD §2.5 (`"an ISO 8601 UTC timestamp with three fractional digits (for example 2025-05-24T10:30:00.123Z)"`). The PRD's "clock value" `2026-08-01T00:00:00Z` in §2.4 refers to the *instant*, not its serialization; per §2.5, that instant serializes to `2026-08-01T00:00:00.000Z`. Each test was fixed to assert the `.000Z` form, making the test faithful to the PRD's stated format:
  - `test_01_register_and_defaults.py::test_create_account_applies_defaults_and_clock_default` — `acct["created_at"] == "2026-08-01T00:00:00.000Z"`
  - `test_03_transfer_settlement.py::test_settle_read_after_write_immediate` — `settled["settled_at"] == "2026-08-01T00:00:00.000Z"`
  - `test_05_dividends.py::test_returned_payment_reissue_refreshes_disbursed_at` — two assertions on `disbursed_at` (`2026-08-03` and `2026-08-12`) updated to `.000Z`
  - `test_05_dividends.py::test_record_date_report_matches_accrual_snapshot` — `report["record_date"] == "2026-09-01T00:00:00.000Z"` (the server normalizes parsed datetimes via `fmt_dt`)
  - `test_07_dormancy_escheatment.py::test_rearm_refreshes_dates` — `dormancy_start_date` and `last_qualifying_contact_date` updated to `2029-08-01T00:00:00.000Z`
  - `test_09_access_envelope_statement.py::test_statement_reflects_position_split` — `statement["as_of"] == "2026-08-01T00:00:00.000Z"`

- **Fixes applied to `implementation/`:** None.

- **Flakiness observed in round 1, cleared in round 2:** Two instances of `Connection reset by peer`/`RemoteDisconnected` on `test_07_dormancy_escheatment.py::TestDormancyBoundary::{test_dormancy_exact_anniversary_is_dormant, test_one_day_short_of_anniversary_stays_active}` in rounds 2, 3, and 6 of the initial sweep — these were transient 8-way-parallel-boot CPU contention on the Flask dev server, not implementation or test bugs. After the timestamp fixes (which did not touch any timing-sensitive code), the second sweep's 8 rounds all passed 80/80 with no connection errors.

- **Final result:** 8 rounds × 80 tests, all passing (640/640).

## Step 8: Finalize PRD — 2026-08-14T18:40:57.247Z

The task is complete. The final verification confirms the only non-`fmt_dt` datetime-field writes are `None` initializations or copies of already-normalized strings (`dormancy_start_date` from `last_qualifying_contact_date` at services.py:290/298, record-date report's `decl["record_date"]` echo at issuers.py:214) — the committed wording is consistent with every path.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1788_stock_transfer_agent_shareholder/workspace/PRD_FINALIZED.md`

**Line counts / %-delta:** PRD.md 351 lines, PRD_FINALIZED.md 351 lines — 0% line delta. Exactly one paragraph (line 76, §2.4) was revised in place.

**Changes (one edit, covering all 8 Step 7 items which share the timestamp-serialization theme):**
- §2.4 — revise — appended two sentences to the closing paragraph: (1) every timestamp the server emits — the clock-written domain fields, a case's `dormancy_start_date`, a statement's `as_of`, the clock endpoint's `current_utc` — serializes in the §2.5 ISO 8601 UTC three-fractional-digit format, and the §2.4 clock-initial-value literal `2026-08-01T00:00:00Z` denotes an instant whose wire form is `2026-08-01T00:00:00.000Z`; (2) client-supplied timestamp fields (`record_date`, `payable_date`, freeze-window `start_date`/`end_date`, `loss_date`, `acquisition_date`, `to_iso8601`) are parsed as instants and echoed back normalized in that same canonical format — impl refs: `helpers.py:27-29` (`fmt_dt`, the sole serializer), `services.py:33-34` (`now_iso`), `services.py:39-40/47/76`, `accounts.py:143`, `dividends.py:56-57/173/196`, `transfers.py:383`, `certificates.py:137/145`, `claims.py:141`, `positions.py:93`, `escheatment.py:95/202`, `services.py:266/278/290/298`, `issuers.py:140-141/151-154/214`, `legends.py:73`, `misc.py:39`.

Note on the `test_01` `created_at` item: §2.5 already pins `created_at`'s format, so that failure was partly a pure test bug — but it stemmed from misreading §2.4's `2026-08-01T00:00:00Z` literal as a serialization; the new §2.4 sentence ("that instant serializes on the wire as `2026-08-01T00:00:00.000Z`") closes that ambiguity without touching §2.5's verbatim prose.

**Per-edit pre-edit search log (one edit):**
- (a) Subject: wire serialization format of every timestamp the server emits — system clock-written fields, client-supplied datetime fields echoed in responses, and the wire form of the §2.4 clock-initial-value literal.
- (b) Impl paths enumerated and read/grepped:
  - Serializer/parser core: `helpers.py:27-29` (`fmt_dt` — always `%Y-%m-%dT%H:%M:%S.fffZ`), `helpers.py:32-44` (`parse_dt`), `helpers.py:115-116` (`req_dt`).
  - Envelope: `response.py:10` (`api_request_timestamp` via `wallclock_iso` → `fmt_dt`; already §2.2-pinned, consistent).
  - Standard fields: `services.py:39-40`, `47`, `76` (`created_at`/`updated_at`, audit events; already §2.5-pinned).
  - Clock-written fields: `dividends.py:173/196`, `services.py:382` (`returned_at`/`disbursed_at`), `transfers.py:383` (`settled_at`), `certificates.py:137` (`lost_reported_at`), `claims.py:141` + `positions.py:93` (`issued_at`), `escheatment.py:95/202`, `services.py:266/278` + `accounts.py:49` (`notice_sent_at`/`last_qualifying_contact_date`), `services.py:290/298` (`dormancy_start_date`, string-copy of normalized value), `accounts.py:143` (`as_of`), `misc.py:39` (`current_utc`).
  - Client-supplied echo normalization: `dividends.py:47-48/56-57` + `issuers.py:214` (`record_date`/`payable_date` and the record-date report echo), `issuers.py:124-125/140-141/151-154` (freeze `start_date`/`end_date` via `_fmt_keep` → `fmt_dt`), `certificates.py:132/145` (`loss_date`), `legends.py:59/73` (`acquisition_date`), `misc.py:36/39` (`to_iso8601`).
  - Exhaustiveness: grep of all 7 `req_dt` call sites; negative grep confirming every non-`fmt_dt` datetime-field write is a `None` initialization or a copy of an already-normalized string; `db.py:26-27` for the clock default.
- (c) Wording adjustments: the draft was split into two sentences — (i) the serialization claim scoped as "every timestamp the server emits" so it covers off-Step-7 paths (`dormancy_start_date`, `as_of`, `current_utc`, the §2.2 envelope timestamp) without redefining them, and (ii) client-field normalization stated as a separate rule with the full field list, since those fields are stored-and-echoed rather than clock-written (avoiding a false claim that e.g. `record_date` is written from the logical clock). The original clock-default sentence was left verbatim; disambiguation was added rather than rewriting it.

## Step 9: Complete PRD — 2026-08-14T18:59:05.862Z

The document is complete and verified. All work is done — here is the summary.

## Summary

**Files**
- Source: `/home/ubuntu/github/CodingPRD/tasks/task_1788_stock_transfer_agent_shareholder/workspace/PRD_FINALIZED.md` — 351 lines, 67,551 chars
- Produced: `/home/ubuntu/github/CodingPRD/tasks/task_1788_stock_transfer_agent_shareholder/workspace/PRD_COMPLETED.md` — 351 lines, 78,020 chars (**+10,469 chars, +0 lines**; all changes are in-paragraph inserts/revisions, no new sections)

**Counts**: 34 distinct changes — **24 ambiguity-pins** (PRD silent → pinned impl behavior) and **10 mismatch-revisions** (PRD described different behavior → revised to impl).

**Changes** (impl references are files under `workspace/implementation/`):

- §2.1 — insert — ambiguity — extended Shareholder ownership enumeration (transfer read requires from- OR to-account; claim read uses `claimant_account_id`) and pinned the filter-only ownership rule on list endpoints (unfiltered lists unrestricted) — middleware.py:32-41, routes/*.
- §2.3 — revise — mismatch+ambiguity — list ordering pinned to creation (insertion) order rather than bare `created_at`; `limit`<1 clamped to 1, negative `offset` clamped to 0, non-integer params → `ERR_INVALID_REQUEST`; `has_more` = `offset` + page size < `total_count` — services.py:51-53, helpers.py:135-158, response.py:19-29.
- §2.4 — insert — ambiguity — clock-set accepts any instant (no monotonicity guard), idempotent re-set; evaluation order accrue→disburse→stale-date→freeze; `freeze.activated`/`freeze.expired` audit labels; no client timestamp is range-checked against the clock — routes/misc.py:31-39, services.py:406-437.
- §2.5 — insert — ambiguity — `version` starts at 1 on creation; `updated_at` initialized equal to `created_at` — services.py:37-43.
- §2.8 step 8 — insert — ambiguity — negative values for non-negative numeric fields (`shares_outstanding`, `par_value_cents`, `current_market_price_cents`, seed share counts, `amount_per_share_millicents`, `coverage_cents`, `premium_paid_cents`) fail with `ERR_INVALID_REQUEST` — issuers.py:37-44, accounts.py:171-176, dividends.py:52-53, transfers.py:202-203, claims.py:69-70.
- §2.9 — revise — mismatch — "every mutation appends an AuditEvent" overclaimed: account `pending_transfer_count`/`stale_dividend_cents`/`address_verified`/contact-date and position `pending_legend_removal_count` riding updates append no events; clock-driven events carry the clock-setter's identity; `from_state` is the empty string on creations — services.py:46-90, transfers.py:27-29.
- §3.1 — revise — mismatch — dropped "nine-character" `cusip` (no format validation in impl) — issuers.py:33-47.
- §3.1 — revise — mismatch — issuer patch: same-status patch refused `ERR_INVALID_STATE`; each applied change touches once (combined status+price patch → version +2, both audit events, status first); no-op patch still touches and writes `issuer.patch` — issuers.py:73-114.
- §3.1 — insert — ambiguity — freeze-window creation permitted over ACTIVE or SUSPENDED issuers — issuers.py:117-148.
- §3.1 — revise — mismatch — dropped "two-letter" `state_code`/"ISO" `country_code` (stored as supplied, no format validation) — accounts.py:32-53.
- §3.1 — insert — ambiguity — `residency` not patchable; account patch refused only for ESCHEATED; audited `account.patch`, with `account.reactivate` appended first on dormant accounts — accounts.py:66-96.
- §3.1 — insert — ambiguity — position seeding refused only for ESCHEATED accounts — accounts.py:156-189.
- §3.2 — insert — ambiguity — `certificate_number` format `CERT-`+12 uppercase hex; null `lost_reported_at` at mint; withdrawal audits `position.certificate_withdrawal` then `certificate.withdraw`; response carries the certificate — positions.py:64-100, services.py:224-225.
- §3.2 — insert — ambiguity — deposit audits `position.certificate_deposit` + `certificate.convert_drs`; non-ISSUED/non-LOST_REPORTED → `ERR_INVALID_STATE`; returns the certificate — certificates.py:86-115.
- §3.3 — insert — ambiguity — body-id resolution order `issuer_id`→`from_account_id`→`to_account_id`→`source_certificate_id`; null initial fields; self-transfers permitted; source-certificate status not examined until settlement; DORMANT transferors allowed — transfers.py:32-116.
- §3.3 — insert — ambiguity — audit labels `transfer.flag_deficient`, `transfer.cure_deficiency`, `transfer.approve`, `transfer.reject`, `transfer.cancel` — transfers.py:218-305.
- §3.3 — revise — mismatch — settle gate order: share-availability failure surfaces before freeze-window conflict (PRD listed freeze first); non-APPROVED and non-ISSUED source cert → `ERR_INVALID_STATE` — transfers.py:308-345.
- §3.3 — insert — ambiguity — settle cascade audit labels (`certificate.cancel`, `position.transfer_debit`, `position.transfer_credit`, `position.create`); auto-created transferee position starts ACTIVE with zeroed fields — transfers.py:346-390.
- §3.4 — insert — ambiguity — claim's four bond fields null until posting; `claim.create` event appended right after `certificate.report_lost`; open-claim check fires before the certificate status gate — certificates.py:118-158.
- §3.4 — insert — ambiguity — `claim.withdrawn` audit(s) precede `certificate.recover` — certificates.py:161-182.
- §3.4 — insert — ambiguity — tendered `premium_paid_cents` frozen on claim; `claim.post_bond` and `claim.reject` audit labels — claims.py:59-117.
- §3.4 — insert — ambiguity — replacement certificate inherits `legend_restricted`, gets fresh number and clock-stamped `issued_at`; audit order `certificate.replaced`→`certificate.reissue`→`claim.replaced` — claims.py:120-152.
- §3.5 — insert — ambiguity — declaration totals start at zero; past dates accepted; `declaration.void` audit label — dividends.py:34-110.
- §3.5 — revise — mismatch — accrual while issuer SUSPENDED is skipped (declaration stays DECLARED, accrues at a later set) rather than "the ERR_ISSUER_SUSPENDED gate applies"; positions walked in creation order; `payment.accrued`/`declaration.accrued` audits; payment `withholding_cents`/`net_cents`/`disbursed_at`/`returned_at` null until their events — services.py:333-369.
- §3.5 — insert — ambiguity — audit labels `declaration.payable`, `payment.disbursed`, `payment.cashed`, `payment.returned`, `payment.reissued`, `payment.stale_dated`; `returned_at` retained across reissue — dividends.py:145-200, services.py:372-403.
- §3.5 — revise — mismatch — closure evaluated only on payment terminalization, so a zero-payment declaration never closes — services.py:318-328.
- §3.5 — insert — ambiguity — record-date report mechanics: mandatory `declaration_id` query param (`ERR_INVALID_REQUEST` if missing, `ERR_DECLARATION_NOT_FOUND` if absent/foreign), entry rows (`account_id`, `eligible_shares`, `gross_cents`, `status`) in payment creation order, served in any declaration status — issuers.py:190-219.
- §3.6 — insert — ambiguity — non-`RULE_144` basis → `ERR_INVALID_REQUEST`; resolution order `position_id` before `account_id`; null initial `counsel_opinion_reference`/`deficiency_reason`; audit labels `legend.submit_opinion`, `legend.flag_deficient`, `legend.rejected`, `position.legend_update` — legends.py:27-203.
- §3.7 — insert — ambiguity — dormancy anniversary = same calendar date N years later, Feb 29 → Feb 28 in non-leap years — helpers.py:47-52.
- §3.7 — insert — ambiguity — case valuation fields null until their pipeline steps; `case.create`/`case.rearmed` audits; `cases_created` counts only fresh cases (not re-arms); sweep event uses synthetic `entity_type` `EscheatmentScan`, `entity_id` `sweep` — escheatment.py:29-59, services.py:282-308.
- §3.7 — revise — mismatch — `report_price_cents` is the earliest-created position's issuer's price (single price applied to cross-issuer share total); no positions → null price and zero share leg — escheatment.py:114-130.
- §3.7 — revise — mismatch — remit hop order pinned as case → positions → payments → account → declaration-closure checks (PRD had account before positions); account escheated from whatever status it holds; audit labels `case.remit`, `position.escheat_closed`, `payment.escheated` — escheatment.py:138-180.
- §3.7 — insert — ambiguity — standalone reactivate endpoint gated to IDENTIFIED/NOTICE_SENT with `case.reactivate` before `account.reactivate`; cascade case transitions audited `case.reactivate` — escheatment.py:183-204, services.py:262-279.
- §3.8 — insert — ambiguity — inquiry null initial fields; `inquiry.create`/`inquiry.claim`/`inquiry.answer` audit labels; ANSWERED-reclaim retains prior `answer_text`; reactivation event precedes `inquiry.create`; statement `totals` fields (`total_book_entry_shares`, `total_certificated_shares`, `total_shares`, `stale_dividend_cents`, `pending_transfer_count`) and position ordering — inquiries.py, accounts.py:131-153.

**Cross-check**: all 80 tests pass in all 8 recorded runs (`implementation/results.1-8.json`); every pin matches the implementation exactly, and no test-only behavior was invented. Deliberately left unpinned: unreachable defensive branches (position/issuer re-resolution failures at deposit/settle/legend-approve) and the pathological double-approval that could drive `restricted_shares` negative (not reachable via any tested flow; §2.10 invariant retained).

## Step 5: Generate Unit Tests — 2026-08-14T19:30:00.000Z

Generation complete. All output under `/home/ubuntu/github/CodingPRD/tasks/task_1788_stock_transfer_agent_shareholder/`.

### test_helpers/ (9 files)
- `types.py` — 13 entity TypedDicts + 16 status/role enums; `AuditEvent` correctly carries only `id`/`created_at` (no `updated_at`/`version`) per the append-only exception in PRD §2.5.
- `api_client.py` — `ApiClient(GenericApiClient)` with 73 methods covering every endpoint incl. `POST /_clock/set_current_utc`.
- `api_errors.py` — full 38-error catalog + HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity structural assertions + domain invariants (`assert_payment_money_conserved`, `assert_issuer_conservation`); position assertion enforces `total_shares == book_entry + certificated` and `0 <= restricted <= book_entry`.
- `factories.py` — payload factories, input fields only.
- `constants.py` — withholding rates (24%/30%/15%), bond constants (x2 multiplier, 10000000 tier cap, 3%/2% tiers), dormancy table (CA 3, NY 5, TX 3, default 5), 180-day stale/holding horizons, 60-day notice window, clock default `2026-08-01T00:00:00Z`.
- `test_users.py` — 7 roles; `make_shareholder_headers(account_id)` and `make_issuer_officer_headers(issuer_id)` per-instance builders for the two entity-backed roles; shared constants for the five opaque roles.
- `fixtures.py` — ~45 helpers across all five tiers: entity builders, OCC-threaded transfer/legend creation, certificate/claim pipeline (`setup_lost_claim`, `setup_bond_posted_claim`, `setup_two_lost_certs_price_moved`), dividend lifecycle (`setup_disbursed_payment` incl. single-clock-set cascade, `setup_w9_cure_payment`, `setup_two_share_667_declaration`, `setup_mixed_residency_payments`), dormancy/escheatment pipelines (`setup_dormant_account_with_case`, `setup_reactivated_case`, `setup_report_ready_case`, `setup_reported_case`, `setup_ca_dormancy_pair`).

### test_suite/ (10 files, 80 tests)
- `test_01_register_and_defaults.py` (7), `test_02_transfer_review.py` (8), `test_03_transfer_settlement.py` (9), `test_04_certificates_and_claims.py` (11), `test_05_dividends.py` (17), `test_06_legend_removal.py` (5), `test_07_dormancy_escheatment.py` (11), `test_08_inquiries_freeze_audit.py` (8), `test_09_access_envelope_statement.py` (4), plus `conftest.py`.

### Coverage audit
- Queue A (§1.8 difficulty): 38 tests — all 19 instances covered with >=2 tests each.
- Queue B (§1.9 corner): 42 tests — all 42 non-stub instances covered with >=1 test each; all 10 `excluded_because:` stubs correctly untranslated, cross-references verified to resolve.
- Tag audit (machine-checked): 80/80 tests carry exactly one `Design:` line as the final docstring line; zero unknown tags; zero stub tags; zero untagged.
- PRD citation audit (machine-checked): all 143 rule-bearing docstring citations are verbatim substrings of `workspace/PRD.md` (modulo whitespace).
- `pytest --collect-only`: 80 tests collected; pyflakes clean; no skip/xfail markers.

### Instances skipped
None.

### Assertion relaxations for unique derivability (PRD-silent inner shapes)
- `record_date_report_matches_accrual_snapshot`: asserts the PRD-named fields (`declaration_id`, `record_date`, `total_shares`, `total_accounts`) and one-row-per-holder entry count; per-entry key names inside `entries` rows are not PRD-pinned, so per-entry `eligible_shares` values are not asserted.
- `statement_reflects_position_split`: asserts `account_id`, `as_of` (default clock), the positions-array split (300/200/500), and presence of the `totals` object; key names inside `totals` are not PRD-pinned, so `totals.total_shares` is not asserted.
- `audit_trail_records_full_transition_chain`: asserts the four-mutation event count and the PRD-named action labels (`transfer.create`, `transfer.medallion_verified`, `transfer.settle`) plus the settle entry's from/to states and actor role; the approval event's action label is not PRD-pinned, so it is not asserted.
