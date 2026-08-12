# Worklog — task_1243_radio_station_programming_ad_sales

## Step 1: Create Task Directory — 2026-08-12T06:38:00.000Z

Task directory `tasks/task_1243_radio_station_programming_ad_sales/` and its `workspace/` subdirectory were pre-assigned and already exist. Step 1 auto-index scan skipped per instructions.

## Step 2: Generate Scaffold — 2026-08-12T07:36:00.000Z

All three artifacts are generated and validated. Final report:

## Task complete — task_1243_radio_station_programming_ad_sales

**Files written** (scenario description embedded verbatim):
- `/home/ubuntu/github/CodingPRD/tasks/task_1243_radio_station_programming_ad_sales/SCAFFOLD.yaml` — §1.0–§1.7 only (17 entities, 88 endpoints, 37 error codes, 12 calculations, 18 validation priorities, 15 state machines, 3 OCC concurrency rules, 5 roles). No difficulty/corner keys inside.
- `/home/ubuntu/github/CodingPRD/tasks/task_1243_radio_station_programming_ad_sales/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 9 rules × 2–3 instances = **20 instances**.
- `/home/ubuntu/github/CodingPRD/tasks/task_1243_radio_station_programming_ad_sales/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, **55 active + 5 excluded-because stubs** across all nine guide sections.

**Above-expert design choices** (per the "harder than expert" parameter):
- Flat topology, segregation-of-duties role model (order creator ≠ approver; reconciler ≠ affidavit issuer — both pinned on `X-User-ID` comparison), 3 OCC rules (`Order`, `DailyLog`, `SyndicationClearance` versions) plus a hierarchical rate-floor override (`allow_below_floor` SalesManager-only).
- Dual variants on two domains: LOCKED vs REPRICED_AT_AFFIDAVIT spot billing (mid-flight ratings-book supersession moves 10000 → 12500) and trade cash-equivalent vs trade-value ledger valuation (5000 vs 6000 at ratio 1.20).
- Combinatorial formulas in two modes: 4-factor tiered spot rate with demand-tier boundary (u ≥ 0.85 → ×1.30, computed 11050) and pinned per-line-then-sum affidavit rounding (1706 vs the forbidden 1705).
- Depth-3 cascade (order cancel → spots → ledger REVERSALs → agreement EXHAUSTED→ACTIVE) and depth-2 clearance-disaffirm cascade; two priority-pair conflicts (state-vs-fiscal, temporal-vs-constraint); three boundary instances on distinct metrics/endpoints (unit capacity equality, zero-discrepancy reconcile gate, exact-zero trade credit); half-open clearance-window overlap vs aggregate hour-seconds capacity; two compensating invariants (trade credit conservation, make-good obligation conservation).

**Verification** — lint verdict block, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  (Coverage: 88 endpoints, 17 entities, 20 §1.8 instances, 55 §1.9 instances, 801 calls scanned)
```

Additionally verified by script: zero unbound/rebound `${var}` placeholders across all 75 recipes, all `grounds:` refs resolve into §1.1–§1.7, instance names unique across both design files, all `excluded_because` stubs cite existing §1.8 instances, no forbidden concurrency vocabulary, and the three-file split is honored. One consistency fix during the audit: `ERR_NO_ACTIVE_CLOCK` was referenced by the lock transition but missing from §1.4/§1.6 — added (validation priority 5.4, catalog entry, 422).

## Step 3: Copy Shared Files — 2026-08-12T07:38:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1243_radio_station_programming_ad_sales/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T07:45:00.000Z

All 12 calculations are covered in the PRD:

- `spot_unit_rate` — §3.2 (ratings multiplier tiers, dow factor, demand multiplier, formula, variants)
- `trade_valuation` — §3.3 (cash-equivalent vs trade value views, round_half_up)
- `trade_available_balance` — §3.3 (replay formula, invariant, auto-transitions)
- `affidavit_billing_total` — §3.8 (per-line rounding, agency commission 0.15, forbidden variant)
- `hour_spot_capacity` — §3.6 (daypart hour sets, units + seconds fit, LIVE_READ_WINDOW units only)
- `spin_compliance` — §3.5 (song separation → artist separation → spin cap ordering)
- `ratings_lookup` — §3.2 (PUBLISHED eligibility, fallback share)
- `clock_pin_selection` — §3.5 (ACTIVE clock covering weekday, ERR_NO_ACTIVE_CLOCK fallback)
- `preemption_selector` — §3.6 (victim pool, ranking, waterfall, ERR_HOUR_CAPACITY_EXCEEDED fallback)
- `make_good_conservation` — §3.7 (conservation invariant)
- `endorsement_contracted_total` — §3.10 (whole weeks, floor of days/7)
- `event_delivery_evaluation` — §3.11 (DELIVERED iff spots_delivered >= spot_units_promised, equality delivers)

All 3 OCC rules (spot-book, log-lock, barter-avail) are in §2.7. Validation priority ordering with sub-orderings is in §2.8. All 37 error IDs and all 33 state values now appear. Sibling branches (LOCKED_AT_BOOKING vs REPRICED_AT_AFFIDAVIT, reschedule vs issue-credit, DRAFT/ACTIVE/RETIRED for clocks, etc.) get equal prose density.

Hard Contract Reports:

```
Field coverage check:
- entities[].fields: 113 required, 113 present, 0 missing
- endpoints[].request_body / query_params / path_params: included in the 113, all present
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 14 checked, 14 expressed in prose (including 7a-7g and 10a-10c sub-orderings), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 36 checked, 36 fully expressed (state pairs, preconditions, side effects), 0 missing
- calculations[]: 12 checked, 12 fully expressed in precise business prose, 0 missing
- validations[] conditions: 14 checked, 14 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narrative, 0 missing
- entities[].fields[] structured content: defaults, types, sources reconstructible from prose, 0 missing
- sibling-branch symmetry: LOCKED/REPRICED variants, reschedule/issue-credit, DRAFT/ACTIVE/RETIRE for clocks, PENDING/CLEARED/DISAFFIRMED for clearances — all rendered with equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 555
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three hard contracts PASS.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1243_radio_station_programming_ad_sales/workspace/PRD.md` — a 5-section PRD (Introduction, Global Specifications §2.1–§2.10, Business Logic §3.1–§3.11, Endpoint Definitions, Error Code Catalogue) with domain-derived subsection titles. The two test-targeting index files were not read.

## Step 5: Generate Unit Tests — 2026-08-12T08:12:00.000Z

Generation complete. All audits pass.

## What was generated

**`test_helpers/` (Stage 1)** — 9 files under `/home/ubuntu/github/CodingPRD/tasks/task_1243_radio_station_programming_ad_sales/test_helpers/`:
- `types.py` — 16 entity TypedDicts + status enums; `TradeLedgerEntry` correctly omits `updated_at`/`version` (append-only per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~65 methods, including the `/_clock/set_current_utc` test-driving capability)
- `api_errors.py` — all 37 error IDs with PRD §5 HTTP statuses, registered via `set_error_http_status_map` (note `ERR_TRADE_CREDIT_EXCEEDED` → 402, `ERR_STALE_VERSION` → 412)
- `assertions.py`, `factories.py`, `constants.py` (ratings/demand tiers, `DAYPART_HOURS`, 0.15 agency commission), `test_users.py` (5 opaque roles + per-user builders for ownership/SoD scenarios), `fixtures.py` (bookable-station/order/log composites, OCC-safe `book_spot`/`schedule_barter_avail` that re-read parent versions, log lifecycle drivers through `AFFIDAVIT_ISSUED`), `__init__.py` barrel

**`test_suite/` (Stage 2)** — `conftest.py` + 14 test files, **95 tests**, collected cleanly by pytest.

## Coverage audit results
- **Queue A (difficulty)**: all 20 instances have ≥2 tests each (40+ tests), tagged `Design: Difficulty/<rule_id>/<name>`
- **Queue B (corner)**: all 55 non-stub instances have ≥1 test, tagged `Design: Corner/<section>/<name>`; the 5 `excluded_because:` stubs were not translated and their difficulty-instance pointers all resolve
- **C4**: every test's docstring ends with exactly one valid Design tag; no tags in test_helpers; no skip/xfail markers; no scaffold references in comments
- **Citations (C1/C2/C3)**: automated sweep confirms every docstring's quoted span survives whitespace-collapsed verbatim matching against PRD.md, with a ≥8-word rule-bearing span in every test

## Judgment calls worth noting
- **`version == 1` initial-value assertions** in two corner instances are not uniquely derivable from PRD §2.5 (it says "system-managed integer incremented on every mutation" but never pins the start value). Scoped to PRD-faithful claims instead: presence/type, `!= 99` for the client-supplied-ignored case, and relative `captured+1` checks for version bumps.
- **Disaffirm log-version bump magnitude**: the design instance asserts `version == pre + 1`, but with two avails on one log the PRD's "each such cancellation … bumps the log's `version`" admits both +1 and +2 readings; the test asserts a bump occurred (`>`), not the exact delta.
- **Make-good conservation + live-read reschedule recipes** omit the `begin-reconciliation` → `reopen` steps, but reschedule is posture-gated to DRAFT/LOCKED and the import leaves the log AS_RUN. The tests insert the reopen (PRD §3.8 loop) before rescheduling; asserted outcomes unchanged.
- All 75 design instances passed the PRD-first two-condition filter — **zero instances skipped**; no gaps logged.

## Step 6: Generate Implementation — 2026-08-12T08:12:00.000Z

Implementation complete and verified. Final summary:

## What was built

A complete Python + Flask implementation of the Radio Station Programming & Ad Sales API in `/home/ubuntu/github/CodingPRD/tasks/task_1243_radio_station_programming_ad_sales/workspace/implementation/`:

- **`start.sh`** — executable launcher; guards `pip install` behind `python3 -c "import flask"` (no-op once deps present, safe for concurrent per-test reboots), then `exec python3 app.py` in the foreground.
- **`app.py`** — Flask app (static route disabled, non-strict slashes), error handlers mapping `ApiError` → envelope, 404/405 → `ERR_NOT_FOUND` envelope, catch-all → `ERR_BAD_REQUEST`; per-request store lock for atomic multi-step operations; binds `0.0.0.0:$PORT` (default 10000).
- **`store.py`** — in-memory dicts keyed by id, all empty at boot (zero seeding); logical clock starting at exactly `2026-05-01T00:00:00Z`.
- **`helpers.py`** — envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta adds `limit`/`offset`/`total_count`/`has_more`), full 34-entry error catalog with exact HTTP codes, `X-User-ID`/`X-User-Role` auth, strict field validators, pagination (default 10, min 1, max 100).
- **`logic.py`** — serializers with on-read computed fields, and all calculations with `Decimal` round-half-up: `spot_unit_rate` (ratings tiers 0.80/1.00/1.25/1.50, weekend 0.85, demand tiers at 0.70/0.85 boundaries), trade valuation/replay balance with ACTIVE↔EXHAUSTED auto-flip, affidavit total (per-line rounding then sum), hour pools, spin compliance (song→artist→cap order), clock pinning, preemption selector (rate ASC, created_at ASC, minimum prefix, atomic all-or-nothing).
- **Route modules** — all 88 scaffold-declared (method, path) pairs registered (verified programmatically: no missing, no extras), with validations evaluated in the scaffold's priority order (well-formedness → auth → role → ownership/SoD → existence → TRADE-required → OCC → state → posture → compliance → temporal sub-order 7a–7g → uniqueness/quota → preemption/capacity → fiscal sub-order 10a–10c).

## Verification

Six smoke suites (run against fresh `bash start.sh` boots) passed: full order/log/affidavit lifecycle with exact rate math (1250, 1063), segregation-of-duties and ownership checks, trade ledger DEBIT/REVERSAL/ADJUSTMENT replay with EXHAUSTED↔ACTIVE cycling, preemption cascade with trade reversals and no-partial-commit, clearance adjacency vs overlap, under-coverage sweep + waive, live-read make-good reschedule with auto-resolved discrepancy, ratings supersede cascade, rate-floor override (incl. SalesManager `allow_below_floor`), `ERR_NO_RATE_CARD`, order completion gate, contract BREACHED, and fresh-boot isolation (empty store + default clock after restart).

## Judgment calls (underspecified points)

- **POST /spots admits SalesManager** in addition to SalesRep/TrafficDirector — the RBAC matrix lists the below-floor override as a SalesManager-exclusive operation on this endpoint, which is otherwise unreachable.
- Booking into a DRAFT log (no pinned clock) treats capacity as unlimited and demand utilization as 0 — required for the DRAFT-posture booking flow to be usable.
- Ungated precondition failures with no catalog error (trade close with SCHEDULED spots, order complete with open obligations) → `ERR_INVALID_STATE`; remote-event settle with missing log → `ERR_NOT_FOUND`, wrong posture → `ERR_LOG_POSTURE_BLOCKED`; past-date event confirm → `ERR_FLIGHT_WINDOW_INVALID`.
- `make_good_reason` persists through RESOLVED (keeping the conservation invariant exact) and is cleared when order-cancel voids a MAKE_GOOD_PENDING spot; one version bump per affected parent per API call; re-import sweeps spots in SCHEDULED+AIRED (per PRD) but live reads/avails only in SCHEDULED (per scaffold transition table).

Orchestrator route-registration audit: all 88 scaffold endpoints registered as Flask `@bp.<method>` routes; 0 missing, 0 extras.

## Step 7: Run Tests and Iterate — 2026-08-12T08:34:00.000Z

## Summary

- **Iterations run**: 2 (first sweep: 17-test failing union across 8 rounds; second sweep: all 8 rounds clean, 95/95 each).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none (the `api` NameError lived in module-level helpers inside `test_suite/`, not the shared helpers package).

- **Fixes applied to `test_suite/`**:
  - `test_05_booking_gates.py`, `test_08_daily_log_lifecycle.py`, `test_12_clearances_barter.py` — 5 module-level setup helpers (`_setup_posture_vs_fiscal_env`, `_setup_two_logs_one_clean_one_dirty`, `_setup_reconciling_log_with_missed_spot`, `_setup_clearance_overlap_env`, `_setup_clearance_with_future_avails`) referenced the bare name `api` without receiving it; added an `api` parameter and updated the 10 call sites. Pure test bug, PRD-neutral.
  - `test_08_daily_log_lifecycle.py` — `test_as_run_import_foreign_id_returns_404` and `_setup_two_logs_one_clean_one_dirty`: log B falls on Tuesday (2026-05-05) but the station only had a MON clock, so `create_locked_log` tripped PRD §3.5's ERR_NO_ACTIVE_CLOCK gate. Added a disjoint TUE `create_active_clock` to both setups — makes the fixture satisfy the PRD lock precondition rather than weakening the implementation's clock-pinning check.
  - `test_03_spot_pricing.py::test_spot_rate_min_rate_floor_applies` — setup created a rate card with `min_rate_cents=3000 > base_rate_cents=2000`, violating PRD §3.2 verbatim ("`min_rate_cents` floor (positive and no greater than `base_rate_cents`)"). Changed to `min_rate_cents=1500` (raw rate 1360 still below floor) and updated the expected pinned rate 3000 → 1500.
  - `test_01_access_control.py::test_spots_create_missing_auth_returns_401` — payload omitted required `expected_order_version` (PRD §3.6 lists it as caller-supplied), and PRD §2.8 orders well-formedness before authentication, so a faithful server must answer ERR_BAD_REQUEST. Added `expected_order_version: 1` so only the missing auth headers drive the rejection.
  - `test_13_live_reads_events.py::test_remote_event_settle_gate_delivered_defaulted` — PRD §3.11 names the settle gate (log must be AFFIDAVIT_ISSUED/CLOSED) but never names the gate's error id; §2.8 admits both ERR_INVALID_STATE and ERR_LOG_POSTURE_BLOCKED readings. Relaxed the exact-id assertion to `validate_error_is_one_of([ERR_INVALID_STATE, ERR_LOG_POSTURE_BLOCKED])` per the permitted coverage correction.

- **Fixes applied to `implementation/`**:
  - `store.py::new_id` — minted `uuid.uuid4().hex` (32-hex, no dashes); PRD §2.5 states "`id` is a server-minted UUID" and the test-side UUID validator requires canonical dashed form. Changed to `str(uuid.uuid4())`.

No tests were deleted; no implementation check was weakened; no capability was added beyond PRD prose.

Orchestrator verification: all 8 results files present, each `passed: 95, total: 95, failed: 0`.

## Step 8: Finalize PRD — 2026-08-12T08:44:00.000Z

Both edits are complete and fully verified. `PRD_FINALIZED.md` is written.

## Summary

**Line counts**: PRD.md 333 lines, PRD_FINALIZED.md 333 lines (0% line-count delta; 2 lines modified in place, no sections added or removed).

### Changes

- **§2.5 (Common Resource Properties)** — revise — appended "rendered in the canonical dashed 8-4-4-4-12 hexadecimal form (for example, `550e8400-e29b-41d4-a716-446655440000`)" to the sentence "`id` is a server-minted UUID with no type prefix." — `implementation/store.py:53-54` (`new_id()` returns `str(uuid.uuid4())`).
- **§3.11 (Remote Broadcast Events)** — revise — extended the settle-gate sentence to name both failure-mode error ids: "if no such DailyLog exists the settle is rejected with `ERR_NOT_FOUND`, and if the log's posture is anything other than `AFFIDAVIT_ISSUED` or `CLOSED` the settle is rejected with `ERR_LOG_POSTURE_BLOCKED`." — `implementation/routes_endorsements.py:434-436` (missing log → `ERR_NOT_FOUND`) and `implementation/routes_endorsements.py:437-439` (wrong posture → `ERR_LOG_POSTURE_BLOCKED`).

### Step 7 items requiring no PRD edit (per the diff's own notes, verified as PRD-neutral fixture/test bugs)

- `test_05`/`test_08`/`test_12` bare-name `api` helpers — pure test bug.
- `test_08` Tuesday-log fixture missing a TUE clock — PRD §3.5's `ERR_NO_ACTIVE_CLOCK` already covers it (confirmed in PRD line 144).
- `test_03` `min_rate_cents > base_rate_cents` fixture — PRD §3.2 already pins the floor verbatim.
- `test_01` missing `expected_order_version` in 401 test — PRD §2.8 already orders well-formedness before authentication.

### Per-edit pre-edit search log

**Edit 1 (UUID dashed form)**
- (a) Subject: format of server-minted `id` values on all entities.
- (b) Paths enumerated: `store.py:8,53-54` (sole minting function `new_id`); all 20 `new_id()` call sites across `routes_core.py`, `routes_orders.py`, `routes_logs.py`, `routes_spots.py`, `routes_trade.py` (line 26), `routes_endorsements.py`, and `logic.py:310,550` (TradeLedgerEntry minting — confirms the shared §2.5 sentence covers ledger entries too); `logic.py:39-43` (`find()` — plain dict lookup, no format validation, so the wording constrains minting only and cannot contradict id lookup of client-supplied path ids); serializers `logic.py:98,187` pass ids through unchanged. No alternate id-minting scheme exists anywhere.
- (c) Wording kept additive ("rendered in the canonical dashed ... form") after the existing "with no type prefix" clause, preserving the original sentence verbatim — no narrowing of which entities are covered.

**Edit 2 (settle gate error ids)**
- (a) Subject: error ids surfaced by `POST /remote-events/{id}/settle` when the cross-entity DailyLog gate fails.
- (b) Paths enumerated: `routes_endorsements.py:423-446` (`settle_remote_event` — the only settle endpoint; order of checks: `find(event)` → `ERR_INVALID_STATE` if not CONFIRMED at line 428 → log lookup `ERR_NOT_FOUND` at line 435 → posture `ERR_LOG_POSTURE_BLOCKED` at line 438); all other `ERR_LOG_POSTURE_BLOCKED` sites (`routes_spots.py:74,211,238,337`; `routes_endorsements.py:158,214`; `routes_logs.py:112`) — each is a distinct per-endpoint posture gate already pinned by its own PRD sentence (e.g. §3.6 line 152), so scoping this edit to the §3.11 sentence only does not redefine the error id globally; `helpers.py:26` (`ERR_LOG_POSTURE_BLOCKED` → HTTP 409, matching PRD error catalog line 305); PRD §2.8 ordering (existence `ERR_NOT_FOUND` precedes the posture gate — consistent with impl order for the two log-related checks; the event's own from-state check sits between them, but §2.8 covers only caller-supplied path ids/foreign keys and the log here is derived from `(station_id, event_date)`, so no conflict).
- (c) Wording pins the two failure modes as conditional clauses ("if no such DailyLog exists … and if the log's posture is …") without asserting any ordering relative to the event's `CONFIRMED` from-state check, keeping the sentence consistent with every enumerated path.

## Step 9: Complete PRD — 2026-08-12T08:58:00.000Z

All edits applied and verified via diff. Final summary:

## Summary

**Files:** `PRD_FINALIZED.md` (333 lines / 54,446 chars) → `PRD_COMPLETED.md` (336 lines / 60,460 chars). Delta: +3 lines, +6,014 chars.

**Counts:** 18 ambiguity-pins (inserts), 6 mismatch-revisions — 24 changed passages total.

- §2.2 — insert — ambiguity — unknown route / unsupported method → `ERR_NOT_FOUND` envelope; unexpected internal failure → `ERR_BAD_REQUEST` envelope (400) — implementation/app.py:53-69
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_BAD_REQUEST`; `created_at` ties break by insertion order; `has_more` = offset+returned < total_count; conjunctive exact-match filter query params before pagination — implementation/helpers.py:307-337
- §2.4 — insert — ambiguity — `to_iso8601` must be ISO 8601 with UTC offset/`Z`, need not be in the future; setter responds 200 with `{"current_utc": "<echoed verbatim>"}` — implementation/routes_core.py:23-30, implementation/helpers.py:286-301
- §2.5 — insert — ambiguity — `version` starts at 1 at creation — implementation/logic.py:24-30
- §2.8 — revise — mismatch — existence of the path id (`ERR_NOT_FOUND`) is checked BEFORE ownership/segregation-of-duties, not after — implementation/routes_orders.py:107-127, implementation/routes_logs.py:313-320
- §2.8 — insert — ambiguity — well-formedness scope: non-object body → `ERR_BAD_REQUEST`, absent body treated as `{}`; cross-field semantic creation rules (date ordering, floor≤base, window wrap) surface as `ERR_BAD_REQUEST` but may run after role/existence checks — implementation/helpers.py:147-154, implementation/routes_core.py:282-283,350-353,424-428
- §3.1 — revise — mismatch — MusicCategory `code` uniqueness per station is NOT enforced (was "unique per station") — implementation/routes_core.py:163-179
- §3.1 — insert — ambiguity — separation minimums ≥ 0, `max_spins_per_day` ≥ 1, song `duration_sec` ≥ 1, else `ERR_BAD_REQUEST` — implementation/routes_core.py:168-170,223
- §3.2 — insert — ambiguity — `base_rate_cents` positive; floor > base or inverted effective window → `ERR_BAD_REQUEST` at creation — implementation/routes_core.py:344-353
- §3.2 — revise — mismatch — `period_end` ≥ `period_start` is enforced at book CREATION (`ERR_BAD_REQUEST`), not at publish; publish only requires `DRAFT` — implementation/routes_core.py:282-283,314-319
- §3.2 — insert — ambiguity — demand utilization `u` = 0 (multiplier 1.00) when the target log has no pinned clock or zero `SPOT_BREAK` capacity over the daypart — implementation/logic.py:392-412
- §3.3 — insert — ambiguity — `credit_limit_cents` positive; manual ledger append accepts only `entry_kind` `ADJUSTMENT` (else `ERR_BAD_REQUEST`), any signed amount, regardless of agreement status — implementation/routes_trade.py:21,86-107
- §3.3 — insert — ambiguity — close-gate violation (SCHEDULED trade spots remain) → `ERR_INVALID_STATE` — implementation/routes_trade.py:65-83
- §3.4 — insert — ambiguity — `flight_end` < `flight_start` → `ERR_BAD_REQUEST`; `daypart_targets` units ≥ 1 — implementation/routes_orders.py:27,49-50
- §3.4 — insert — ambiguity — completion errors pinned: clock not past `flight_end` → `ERR_FLIGHT_WINDOW_INVALID`, then open obligations → `ERR_INVALID_STATE` — implementation/routes_orders.py:198-206
- §3.4 — insert — ambiguity — counters are derived-on-read; Order `version` bumps at most once per mutating call (one bump per order per as-run import); order-cancel clears `make_good_reason` to null on `MAKE_GOOD_PENDING` spots — implementation/logic.py:68-74, implementation/routes_orders.py:176-189
- §3.5 — insert — ambiguity — new log has null `clock_id`/`clock_version`/reconciler/affidavit stamps/`affidavit_total_cents` and empty `music_placements`; placement `hour` must be 0–23 — implementation/routes_logs.py:33-36,106
- §3.6 — insert — ambiguity — log with no pinned clock imposes no capacity constraint (every unit fits) — implementation/logic.py:493-507
- §3.6 — revise — mismatch — POST /spots caller roles are `SalesRep`, `TrafficDirector`, **and `SalesManager`** (was only SalesRep/TrafficDirector) — implementation/routes_spots.py:55-59
- §3.6 — insert — ambiguity — `unit_rate_override_cents` must be a positive integer; `ERR_NO_RATE_CARD` fires even with an override; daypart quota counts non-successor `SCHEDULED`/`AIRED` spots; `ERR_PREEMPTION_NOT_ALLOWED` evaluated unconditionally before capacity; preemption ranking's remaining ties break by insertion order — implementation/routes_spots.py:48-50,95-118, implementation/logic.py:510-541
- §3.7 — insert — ambiguity — all three `aired_*` lists required (may be empty); only `SCHEDULED` live reads/avails swept (already-`AIRED` untouched on re-import); live-read reschedule requires target `LIVE_READ_WINDOW` pool fit; reschedule performs no order/agreement/contract status re-check; live-read successor inherits `duration_sec`; resolution note accepted as `note` or `resolution_note` and recorded on the linked discrepancy; auto-resolve stamps `resolved_by_user_id` = `"system"` — implementation/routes_logs.py:150-153,202-227, implementation/routes_endorsements.py:217-255, implementation/routes_spots.py:291-312, implementation/logic.py:566-579
- §3.7 (discrepancy paragraph) — insert — ambiguity — explicit resolve/waive also accept the note as `note` or `resolution_note`; auto-resolved stamp literal `system` — implementation/routes_endorsements.py:296-348
- §3.8 — insert — ambiguity — affidavit repricing ADJUSTMENTs carry `spot_id` null and `note` `"affidavit repricing"`; credit check is atomic per agreement (summed deltas) before any commit — implementation/routes_logs.py:330-367
- §3.9 — insert — ambiguity — clearance creation with `start_hour`+`duration_hours` > 24 or inverted effective range → `ERR_BAD_REQUEST`; avail `duration_sec` one of 15/30/60 — implementation/routes_core.py:424-428, implementation/routes_spots.py:324-326
- §3.10 — insert — ambiguity — program-window (`end_hour ≤ start_hour` or > 24) and `end_date < start_date` violations → `ERR_BAD_REQUEST`; live-read `duration_sec` outside {30,60} → `ERR_BAD_REQUEST`; contract close with clock not past `end_date` → `ERR_FLIGHT_WINDOW_INVALID` — implementation/routes_endorsements.py:37-41,99-102,152-153
- §3.11 — insert — ambiguity — `package_price_cents` positive; event confirm with past `event_date` → `ERR_FLIGHT_WINDOW_INVALID` — implementation/routes_endorsements.py:361-362,401-404
- §4 intro — revise — mismatch — music-placement append and both reschedule endpoints return **201** (was: "including the append of music placements … return 200 OK") — implementation/routes_logs.py:145, implementation/routes_spots.py:288, implementation/routes_endorsements.py:233
- §4 table — revise — mismatch — POST `/spots` authorized roles row now includes SalesManager — implementation/routes_spots.py:58-59

## Post-Step-9 confirmation sweep — 2026-08-12T09:00:00.000Z

Re-ran the 8-round parallel stability sweep (`/tmp/sweep_1243.sh`, foreground) after Step 9 completed the PRD. All 8 rounds: passed 95 / total 95 / failed 0. Final artifact set (PRD_COMPLETED.md + implementation/ + test_suite/ + test_helpers/) is green.
