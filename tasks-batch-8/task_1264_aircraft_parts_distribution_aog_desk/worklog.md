# Worklog — task_1264_aircraft_parts_distribution_aog_desk

## Step 1: Create task directory — 2026-08-12T00:00:00.000Z

Pre-assigned by launcher: `tasks/task_1264_aircraft_parts_distribution_aog_desk/` and its `workspace/` subdirectory already exist. Step 1 auto-index scan skipped per instructions. Treating as done.

## Step 2: Generate scaffold — 2026-08-12T12:56:00.000Z

Scaffold generation complete. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_1264_aircraft_parts_distribution_aog_desk/` and the linter verdict is clean.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    66
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     46
  Calls scanned (§1.8+§1.9):  595

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was built

**Difficulty calibration** — "harder than expert" applied per §0.4 (guidelines, not hard caps): 14 entities, 66 endpoints, 45 error codes, 10 calculations (3 dual-variant pairs), 11 state machines, 3 OCC concurrency rules — exceeding the Expert band (10–15 entities / 20–32 endpoints / 18–30 errors) on every axis while keeping coupling dense rather than broad.

**Design highlights**
- Profile: `compliance_audit` primary + `pricing_engine` secondary; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; flat topology (all peer entities, FK-linked); `segregation_of_duties` role model (warranty review vs approve; compliance vs warehouse).
- All 9 Difficulty Rules with ≥2 instances (19 total): dual-variant on CoreReturn penalty (provisional forfeiture 500000 vs final accrual 57500) and Loan-vs-Lease settlement (937500 vs 1500000 for identical dates); combinatorial formulas covering all three modes (per-line rounding 107974-vs-107973; pre-fee handling bracket 9500-vs-4500 divergence; freight 413406 via weight×distance×mode×hazmat×escalation); cyclic Quote revision loop + parallel SalesOrder dimensions; depth-4 delivery cascade and depth-3 lease-sweep suspension cascade; state-vs-fiscal and temporal-vs-constraint priority conflicts; credit-equality and zero-days-overdue boundaries; loan half-open vs charter 120-minute-buffer overlap semantics; deposit-waterfall money conservation and allocate/release unit-count conservation.
- §1.9 corner design: 47 instances (45 active + 2 excluded_because stubs) across all nine guide sections, including 3 OCC stale-version negative tests, FIFO sourcing selector, tier-progression boundary, warranty/restocking tier math, and RBAC denials.
- Deterministic testability: logical clock endpoint with mandatory `2026-05-01T00:00:00Z` startup default, monotonic set, and a pinned-order `/aog`-external `_system/run-sweeps` ops checkpoint.
- Every numeric assert in both design files was pre-computed by executing the formulas (verified via Python); every `${var}` placeholder traces to a prior `captures:` (machine-checked), and no forbidden race vocabulary appears anywhere.

One design repair worth noting: mid-build I found and fixed a self-inconsistency — desk-direct loans originally required unit `AVAILABLE`, which would have masked the half-open overlap rule behind a state check; the loan book (not unit status) is now the schedule arbiter for desk-direct loans.

## Step 3: Copy shared files — 2026-08-12T12:57:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T13:25:00.000Z

The PRD is complete and all verifications pass.

## Summary

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1264_aircraft_parts_distribution_aog_desk/workspace/PRD.md` (350 lines) from `SCAFFOLD.yaml` (14 entities, 66 endpoints, 45 error codes, 10 calculations, 11 state machines, 3 OCC rules). The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, and no sibling tasks were consulted.

**Document skeleton (domain-derived, not template-copied):**
- §2: RBAC with per-role `identity:` prose, verbatim §2.2 envelope block (verified byte-for-byte against the canonical source), pagination, common resource properties (with the `AccountLedgerEntry` `common_fields: false` exception), append-only ledger, integer-cents/round-half-up + 86,400-second day / 30-day month grid, trace-doc ranks 0–4, hazmat/export/denied-destination gates, three OCC rules, the logical clock, and a numbered 10-priority validation-order subsection.
- §3: nine subsections organized by business timeline (customer standing → catalog/inventory → AOG sourcing → quoting → fulfillment → core returns → loans/leases → warranty/returns → sweep), with all formulas rendered as reconstructible prose (pinned rounding orders, freight weight×distance×mode matrix, dual-variant core penalty and loan settlement, tier thresholds, FIFO sourcing selector).
- §4: 4-column table, all 66 endpoints. §5: 2-column table, all 45 error IDs.

**Hard contract reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs/query/path params: 126 required (deduped), 126 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: 10 priorities expressed in numbered §2.11 prose
- concurrency_rules[] OCC rejections: 3/3 expressed (write capability + expected_<parent>_version + exact error_id + 412)
- state_machines[].transitions: all from/to state tokens present; every precondition→error_id and side effect (incl. delivery, BLOCKED, accept-explosion, cancel, sweep cascades) expressed
- calculations[]: 10/10 expressed, including PROVISIONAL/FINAL penalty and LOAN/LEASE settlement variants
- validations[] conditions: all 45 error IDs matchable to triggers in §2/§3 prose
- endpoints[].side_effects / applies_to: expressed (verified all 66 paths in §4)
- entities[].fields[] structured content: defaults/initials reconstructible (core_value_cents 0, warranty_months 12, revision_count 0, version 1, tier STANDARD, etc.)
- sibling-branch symmetry: verdicts, decisions, damage_flag, condition_grade, variants rendered at equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 643
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional hygiene checks: zero operator/pseudocode leakage (`==`, `>=`, `min(`, `->`, …) and zero fuzzy hedging words ("approximately", "roughly", …) in §1–3 prose; all 8 role names spelled exactly; all 44 state values present as exact UPPERCASE strings.

## Step 5: Generate unit tests — 2026-08-12T13:55:00.000Z

Generation complete. 84 tests collected cleanly across 11 test files, with full infrastructure.

## Deliverables

**`test_helpers/`** (Stage 1) — all under `/home/ubuntu/github/CodingPRD/tasks/task_1264_aircraft_parts_distribution_aog_desk/test_helpers/`:
- `types.py` — 25 enums + 14 TypedDicts; `AccountLedgerEntry` correctly omits `updated_at`/`version` (append-only)
- `api_client.py` — 44 endpoint methods (all of PRD §4 incl. `/_clock/set_current_utc` and `/_system/run-sweeps`)
- `api_errors.py` — 45 error IDs with HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity validators + `assert_core_return_waterfall_invariant`
- `factories.py`, `constants.py`, `test_users.py` (with mandatory `make_customer_headers(customer_id)` for the entity-backed CustomerContact role), `fixtures.py` (composite chains: `setup_issued_quote`, `setup_delivered_order`, `setup_delivered_multi_line_order`, accept/allocate/compliance/shipment helpers)

**`test_suite/`** (Stage 2) — `conftest.py` + 11 files (test_01 security/envelope … test_11 sweeps), **84 tests, 0 collection errors**.

## Coverage audit
- **Queue A (difficulty): all 19 instances covered, ≥2 tests each** (42 tests).
- **Queue B (corner): 44 of 46 non-stub instances covered.** Both `excluded_because` stubs verified — pointers resolve to real difficulty instances, not translated.
- Every test docstring: verbatim PRD citation (all 84 pass literal-grep against `PRD.md`) + exactly one terminal `Design: Difficulty/...` or `Design: Corner/...` line resolving to a real instance. No skip/skipif/xfail markers.

## Two intentional gaps (PRD-first filter failures)
1. `Corner/endpoints/quote_create_rejects_extra_computed_field` — the PRD's §2.11 malformed-payload list (missing field, invalid enum, non-positive quantity, malformed timestamp, forbidden field combination) never names unknown/computed-field rejection; a PRD-only implementer could silently ignore extra fields. Not uniquely derivable.
2. `Corner/cross_cutting_layers/lease_period_boundary_inclusive` — asserts the sweep posts a period debit at *exactly* the 30-day boundary instant, but PRD §3.9 says debits post "for every 30-day boundary crossed since the last posting"; unlike the explicit strictness words elsewhere ("past its due_at", "strictly after"), "crossed" admits both `>=` and `<` implementations.

## Two pre-computed literals in §1.8 corrected to PRD-derived values
The difficulty YAML's arithmetic was off by 30 cents in two balance assertions (it implied a quote total of 269740 instead of the PRD-pinned 269770 = 250000 + 4500 handling + 15270 tier fee). Tests assert the PRD-derivable values: post-delivery balance **774570** (not 774540) in `delivery_cascade_invoice_to_balance`, and post-waterfall balance **312070** (not 312040) in `core_deposit_waterfall_conservation`. Hard-coding the YAML literals would have failed any PRD-faithful implementation.

## Step 6: Generate implementation — 2026-08-12T13:55:00.000Z

Implementation complete. All files are in `/home/ubuntu/github/CodingPRD/tasks/task_1264_aircraft_parts_distribution_aog_desk/workspace/implementation/`.

## What was built

A Python + Flask in-memory REST API implementing all 66 endpoints from the scaffold:

- **`start.sh`** — guarded install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), boots in ~1s, store empty on every boot (per-test-server safe).
- **`app.py`** — Flask entry, ApiError/404/405/500 envelope handlers, blueprint registration.
- **`db.py`** — empty-per-boot store + logical clock (starts exactly `2026-05-01T00:00:00Z`, monotonic) + a monotonic stamp source guaranteeing unique `created_at` values (required by the FIFO sourcing rule).
- **`util.py`** — exact scaffold envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination `limit`/`offset`/`total_count`/`has_more` in meta), ms-precision ISO timestamps, payload validators, round-half-up via `Decimal`.
- **`auth.py`** — `X-User-ID`/`X-User-Role` (401 `ERR_UNAUTHENTICATED`), per-endpoint role gates (403 `ERR_FORBIDDEN`), CustomerContact ownership + list scoping.
- **`calc.py`** — all 10 calculations: per-line round-then-sum pricing, pre-fee-subtotal handling brackets (9500/4500/0), tier fees (6%/3%/0%), freight (weight×distance brackets, CHARTER `max(750000, 2900·km)`, HOT_SHOT +250000, ×1.25 hazmat, ×1.25 escalation, single final rounding), core-penalty PROVISIONAL/FINAL variants, LOAN (1.5× late tier) vs LEASE (whole-period, no late mult) settlement, tier recompute, restocking fee, balance aggregation.
- **`routes/`** — 11 modules covering customers (OCC credit-adjustments, suspend/reactivate, newest-first ledger), catalog (duplicate-serial, trace upgrade no-downgrade), AOG requests (FIFO source-search with pin release, escalate, cascading cancel), quotes (cyclic DRAFT→ISSUED→REJECTED/EXPIRED→DRAFT, lazy expiry, OCC, credit-exposure gate with equality passing, accept cascade exploding lines per unit), orders (parallel fulfillment/compliance/payment dimensions, BLOCKED release cascade), allocate/release (pin-claim semantics, condition + trace-rank gates), shipments (charter-field rules, 120-min diary, tender gates in PRD order, full delivery cascade: invoice/deposit debits, CoreReturn per EXCHANGE line, LoanAgreement per LOAN/LEASE line with LEASE activation debit, unit SOLD/ON_LOAN, slot release, auto-close), core returns (deposit waterfall with waiver math and settlement invariant), loans (half-open overlap, sweep boundary debits, damage path), warranty (segregation of duties, reopen cap 1, fraud flags), RMAs (30-day window, 10%/20% restock), and the platform clock + 6-step pinned sweep.

## Verification

Five self-written end-to-end batteries ran green against the live server, covering: the full happy path (request → search → quote → issue → accept → allocate → clear → tender → deliver → core settle → auto-close) with exact cent assertions; expiry/lazy-expiry/revise cycles and tier caps; LEASE activation + sweep debits + return settlement (600000 cents case); LOAN late-tier billing (130000 case); charter floor/overlap/buffer boundary; hazmat/export/denied-destination tender gates; credit-limit 402 with equality; warranty SoD/coverage/reopen-cap; RMA RESALEABLE/DAMAGED paths; sweep expiry with pin release; PLATINUM tier promotion; pagination envelope; auth/RBAC/404 error-id spot checks; and fresh-boot empty-store via `bash start.sh`.

One design call worth noting: entity `version` increments once per state-machine transition, so same-request fall-throughs (tender → IN_TRANSIT, approve → CREDIT_ISSUED, loan RETURNED → SETTLED, RMA RECEIVED → SETTLED) advance the version twice, consistent with PRD §2.4's "any state transition is a mutation."

Orchestrator verification: implementation registers exactly the 66 (method, path) route pairs declared in SCAFFOLD.yaml §1.5 — no missing, no extras. 84 tests collected with 0 errors.

## Step 7: Run tests and iterate — 2026-08-12T14:35:00.000Z

## Summary

**Final state: all 8 parallel rounds pass 84/84 — verified in two consecutive clean sweeps.**

### Iterations run: 5 sweeps
- **Sweep 1** (baseline): 80/84 × 8 rounds — 4 consistent failures.
- **Sweep 2**: 4 original failures fixed; 1 new infrastructure error (`test_aog_cancel_releases_reserved_unit` errored 8/8 on the runner's 15s per-test server-restart poll expiring — a boot-stall flake, not an assertion failure; the test had passed 8/8 in sweep 1).
- **Sweep 3**: all green, but boot logs exposed that my temporary retry-loop start.sh caused a respawn storm (2691 EADDRINUSE entries: the runner kill -9s the listen pid, the surviving bash loop respawned competing servers). Reverted to exec form.
- **Sweep 4**: clean 8/8; boot logs show exactly 85 clean boots/round, zero errors.
- **Sweep 5** (confirmation): clean 8/8.

### Tests deleted: none.

### Fixes applied to `test_suite/`
1. **`test_06_quote_lifecycle.py::test_cycle_statuses_and_revision_count` and `::test_reissue_rearms_validity_clock`** — TEST WAS WRONG (STEP 2): both drove the quote-revision cycle with `validity_hours: 48` on a fresh customer. PRD §3.1 states a new customer starts STANDARD, and §3.4 states verbatim "the `validity_hours` to fit the cap of the tier in effect at issue time — 24 hours for `STANDARD`, 48 for `PRIORITY`, 72 for `PLATINUM` — with an over-cap window refused as `ERR_VALIDITY_EXCEEDS_TIER_CAP`". A PRD-faithful implementation must refuse the re-issue (implementation was correct). Fixed the revise payload to 12 hours — inside the STANDARD cap yet distinct from the original 24h, so the re-arm assertion still discriminates revised-vs-stale validity — and updated the expected expiry to `2026-05-01T12:00:00Z` / `timedelta(hours=12)` plus docstrings.
2. **`test_07_fulfillment_compliance.py::test_delivery_advances_fulfillment_and_payment` and `::test_payment_credit_moves_payment_alone`** — STEP 1b unique-derivability collapse (vacuous-truth ambiguity): PRD §3.5 states the delivery cascade ends with fulfillment "reaches `DELIVERED`" and separately "once every core return and loan born of the order has settled, the order's fulfillment moves `DELIVERED` → `CLOSED` … automatically". For an OUTRIGHT-only order the settle-set is empty, so two PRD-faithful readings diverge (immediate auto-close on the vacuously-true condition vs. settlement-triggered closure; the withheld scaffold assumed the latter, the implementation the former). Per STEP 1c, kept all covered assertions (payment `INVOICED`/`PAID`, `invoiced_cents == 110_770`, compliance untouched) and relaxed only the fulfillment assertion to `in ("DELIVERED", "CLOSED")` with a rationale comment.

### Fixes applied to `test_helpers/`: none.

### Fixes applied to `implementation/`
- **`workspace/implementation/start.sh`** only: added boot logging (`BOOT_LOG`, defaults to `/dev/null`, stderr captured) used to diagnose the sweep-2 restart flake; no API/logic change. No implementation logic was touched — the implementation was PRD-faithful on all 4 assertion failures.

### Infrastructure
- Created `/home/ubuntu/github/CodingPRD/tasks/task_1264_aircraft_parts_distribution_aog_desk/run_sweep.sh` per the headless-run constraints (8 concurrent rounds, `wait`, result-file poll, verbatim `cd … && bash start.sh` start command).

## Step 8: Finalize PRD — 2026-08-12T14:45:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1264_aircraft_parts_distribution_aog_desk/workspace/PRD_FINALIZED.md` written with exactly one edit.

## Summary

**Line counts:** PRD.md 350 lines, PRD_FINALIZED.md 350 lines (0% delta; one sentence replaced in-line with a longer sentence, no lines added/removed).

**Changes (one bullet per change):**
- **§3.5 (final "Closure" paragraph)** — revise — pinned the evaluation timing of the order-closure condition: it is checked at the end of the delivery cascade itself and again at each subsequent core-return/loan settlement, so an all-`OUTRIGHT` order (empty settle-set) closes `DELIVERED` → `CLOSED`, and its request closes `FULFILLED` → `CLOSED`, inside the delivery request itself — `workspace/implementation/helpers.py:136-156`, `workspace/implementation/routes/shipments.py:218,288-300`, `workspace/implementation/routes/core_returns.py:142`, `workspace/implementation/routes/loans.py:171-175`.

**Step-7 items disposition:**
- `test_06` fix (validity_hours 48 → 12 on STANDARD tier): pure fixture bug — PRD §3.4 already uniquely determines the tier-capped validity at issue; implementation was PRD-faithful. No PRD edit.
- `test_07` fix (fulfillment `in ("DELIVERED", "CLOSED")`): genuine PRD vacuous-truth ambiguity; implementation deterministically closes immediately. Pinned to implementation behavior (not the relaxed test range) via the one edit above.
- `start.sh` boot logging: no API/logic change. No PRD edit.

**Per-edit pre-edit search log (the single edit):**
- (a) Subject: evaluation timing of the `DELIVERED` → `CLOSED` order-closure condition (and the `FULFILLED` → `CLOSED` request cascade) when the order's derived core-return/loan settle-set is empty.
- (b) Impl paths enumerated and read/grepped: `helpers.py:136-156` (closure helper; `all()` over empty lists → vacuous true); `routes/shipments.py:195-301` (deliver cascade: sets `DELIVERED` at :218, request `FULFILLED` at :291-292, calls `maybe_close_order` at :300 — same-request closure); `routes/core_returns.py:140-142` (inspect-settle trigger); `routes/loans.py:171-175` (loan return-settle trigger, gated on `order_line_id` so desk-direct loans never close orders); `routes/system.py` (sweep — no closure logic, confirmed by grep); `routes/orders.py:200` and `routes/requests.py:146` (read-only guards mentioning CLOSED, unaffected).
- (c) Wording adjustments: (i) phrased as a *condition evaluated at delivery and at each settlement* rather than "closes at delivery", so the settlement-triggered paths (core_returns.py:142, loans.py:175) for EXCHANGE/LOAN/LEASE orders remain correctly described; (ii) scoped "loans" to "those born of the order" so desk-direct loans (which never trigger `maybe_close_order`) are not implicated; (iii) avoided naming the sweep as a closure trigger, since `system.py` contains none; (iv) kept §3.3's restatement ("a fulfilled request closes automatically once every core return and loan derived from its order has settled") verbatim — it remains true under vacuous truth and the §3.5 pin now governs timing.

## Step 9: Complete PRD — 2026-08-12T15:10:00.000Z

Done. `PRD_COMPLETED.md` is written and verified (no lingering `EXCEPTION` references; diff is purely additive prose plus one deletion).

## Summary

**File delta:** `PRD_FINALIZED.md` 350 lines / 62,170 chars → `PRD_COMPLETED.md` 352 lines / 66,297 chars (**+2 lines, +4,127 chars**).

**Counts:** 27 ambiguity-pins, 5 mismatch-revisions (32 changes total).

### Mismatch revisions (PRD described behavior impl does not exhibit)

- **§2.11** — revise — mismatch — "400 before any business-rule evaluation" replaced: payload validation runs after auth/role checks, at the point each endpoint reads the field, always before gates 7–10 but interleaved with ownership/existence/state/OCC per endpoint; undeclared fields are ignored (`routes/quotes.py:222-242`, `routes/tender` equivalent at `shipments.py:135-148`).
- **§3.3** — revise — mismatch — "An empty pool changes nothing: the request stays OPEN" → an empty pool makes no new reservation but any earlier pin stays released, the request may be `QUOTED`, and `version` advances only on actual change (`routes/requests.py:116-132`).
- **§3.5** — revise — mismatch — deleted the "48 hours past `arrive_at` → sweep marks `EXCEPTION`, re-tender to `IN_TRANSIT`" sentence; no such sweep step exists (`routes/system.py:37-137` has six steps, none touching shipments).
- **§3.5** — revise — mismatch — `decision_memo` is accepted but not persisted on the order (`routes/orders.py:56-85`; `ser_order` has no memo field).
- **§3.8** — revise — mismatch — `review_notes` is accepted but not persisted on the claim (`routes/warranty.py:92-107`; `ser_claim` has no notes field).

### Ambiguity pins (PRD silent; pinned to impl)

- **§2.3** — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; out-of-range values clamped, not rejected (`util.py:138-150`).
- **§2.4** — one request walking multiple transitions bumps `version` per transition; entity timestamps read from the logical clock (`helpers.py:9-11`, `db.py:35-42`).
- **§2.5** — zero/negative computed postings append no ledger entry (`helpers.py:64-69`).
- **§2.9** — expected-version fields on non-OCC endpoints are ignored.
- **§2.11 gate 4** — added `ERR_COMPLIANCE_NOT_CLEARED`, `ERR_REOPEN_LIMIT_REACHED`; lazy expiry affects transitions only — stored status stays `ISSUED` until the sweep (`helpers.py:91-96`).
- **§2.11 gate 9** — added `ERR_DUPLICATE_SHIPMENT` (`shipments.py:67-70`).
- **§3.1** — `CustomerContact` sees only their own row in the customer directory (`customers.py:47-48`).
- **§3.2** — duplicate `part_number` → `ERR_INVALID_REQUEST` (`catalog.py:48-51`).
- **§3.3** — source-search permitted from `OPEN` or `QUOTED` (`requests.py:113-115`); escalation permitted from any status but `CANCELLED`/`CLOSED` (`requests.py:146-148`); contact canceling a `QUOTED` request → `ERR_FORBIDDEN` (`requests.py:163-165`).
- **§3.4** — drafting requires an `OPEN`/`QUOTED` request; customer mismatch → `ERR_INVALID_REQUEST`; `unit_price_cents` may be zero (`quotes.py:126-131, 47-48`); acceptance moves the quote `ISSUED` → `ACCEPTED` and the order is born with `invoiced_cents` zero (`quotes.py:249-285`); rejecting a lapsed quote → `ERR_INVALID_STATE` (`quotes.py:294-296`).
- **§3.5** — allocation requires fulfillment `PENDING_ALLOCATION`/`ALLOCATED`; wrong-part unit → `ERR_UNIT_NOT_AVAILABLE`; the `RESERVED` exception also covers an explicitly named pinned unit; allocating the pin clears both pin fields (`orders.py:137-181`); shipment creation has no order-state gate, booking a `RELEASED` slot → `ERR_INVALID_STATE`, the diary check spans every shipment ever created for the slot, tender-supplied refs persist, duplicate `tail_number` → `ERR_INVALID_REQUEST`, re-releasing a `RELEASED` slot → `ERR_INVALID_STATE` (`shipments.py:32-103, 145-148, 312-314, 358-360`).
- **§3.6** — receipt refuses a duplicate core serial with `ERR_DUPLICATE_SERIAL`; inbound unit is `TRACE_MISSING` and inherits the delivered unit's `warehouse_code` (`core_returns.py:66-84`); penalty is zero while `OVERDUE`, so waivers only succeed once `RECEIVED` (`core_returns.py:88, 155-160`).
- **§3.7** — window violations split: past start / due-not-after / lease-horizon → `ERR_LOAN_WINDOW_IN_PAST`, `lease_periods` shape → `ERR_INVALID_REQUEST`; non-rotable unit → `ERR_INVALID_REQUEST` (`loans.py:34-67`); unit transitions at return apply only to a unit actually `ON_LOAN` — desk-direct loans of `AVAILABLE` units leave the unit untouched (`loans.py:156-170`).
- **§3.8** — claim against a foreign or undelivered line → `ERR_INVALID_REQUEST` (`warranty.py:37-43`); `coverage_pct` carried as a fraction (1 / 0.75 / 0.5 / 0), zero until approval (`warranty.py:58, 128-132`); RMA window measured in whole floor days with day 30 inclusive (`rmas.py:40-44`); receipt is not re-checked against the window — day-31+ arrivals still draw the 20% fee (`rmas.py:99-102`, `calc.py:114-116`).
- **§3.9** — lease forward billing covers `ACTIVE` and `OVERDUE` leases (`system.py:83-94`); `tiers_updated` counts only customers whose tier actually changed (`system.py:118-121`).
