# Worklog — task_0302_farmers_market_vendor_booth

## Step 1: Create Task Directory — 2026-06-11T22:27:00.000Z

Created `tasks/task_0302_farmers_market_vendor_booth/` and `tasks/task_0302_farmers_market_vendor_booth/workspace/` using the pre-allocated index 0302 (no scan/auto-increment per orchestration override). Scenario: Farmers Market & Vendor Booth Management. Difficulty target: Expert (passed only to Step 2 scaffold generator).

## Step 2: Generate Scaffold (Expert band) — 2026-06-11T22:54:00.000Z

All three files are correctly structured. SCAFFOLD.yaml contains §1.0–§1.7 (no design keys), and the two design files each carry their single top-level key.

The scaffold generation is complete. Here is the summary.

## Summary

Generated a complete Expert-band scaffold package for **Farmers Market & Vendor Booth Management** at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0302_farmers_market_vendor_booth/`. All three files pass `scaffold_lint.py` with **VERDICT: clean lint** (536 §1.8+§1.9 calls conform to §1.5; all 21 FKs reverse-reachable).

**Complexity profile**: primary archetype *quota/allocation* + secondary *ledger reconciliation*; layers = dual-variant calculation, cascading side effects, optimistic concurrency, derived-field reconciliation. Topology = **flat** (FK-linked peers, `api_prefix: /`, prioritized as 0%-in-examples), shape = **branching** (cycles on Application and SalesReport), role model = **peer_roles**.

**SCAFFOLD.yaml (§1.0–§1.7)** counts:
- **11 entities** (Market, Vendor, Permit, Application, Booth, MarketDay, BoothAssignment, CheckIn, SalesReport, VoucherBatch, VoucherRedemption)
- **6 state machines** — Application (cyclic reject→resubmit), BoothAssignment (branching allocation + waitlist promotion), MarketDay (weather-cancellation master cascade), CheckIn, SalesReport (cyclic dispute loop), VoucherRedemption
- **6 calculations** — `assignment_fee` (dual-variant season vs daily), `commission` (dual-variant provisional gross vs final token-reconciled), `market_fee_ledger` (pinned-eval-order combinatorial), `voucher_liability_ledger` (≥3-input nested-min combinatorial), `fee_refund`, `waitlist_rank`
- **13 validations** (priority-ordered, 8 categories)
- **51 endpoints** (flat CRUD + lifecycle actions + filtered-list reverse-reachability GETs + 1 `/_clock` test-driving endpoint)
- **18 error codes**
- **3 roles** — MarketAdmin (opaque), MarketManager (opaque), Vendor (entity_backed:Vendor)
- **1 concurrency rule** — `season-assignment-stale-booth` (OCC on Booth.version, CREATE-with-supersede, 412)

**Expert-band depth (§1.8)**: all 9 Difficulty Rules × exactly 2 instances = **18 instances**, each with full setup_api_calls + trigger + assert chains and pre-computed literal expectations. Differentiation verified: dual-variant on different entity domains (BoothAssignment fee / SalesReport commission); combinatorial across modes (a) and (c); cycles on two different entities; cascades depth-3 (weather cancel) and depth-2 (complete→promote) from different triggers; priority pairs (safety/constraint, state/fiscal); boundaries on different metrics (token cap / empty-set); cross-entity deps on different pairs (App→Permit, SalesReport→Redemption); overlap on different resource entities with different interval semantics (Booth date-range / VoucherBatch aggregate-capacity); compensating invariants on two conserved quantities (voucher cash liability / occupancy-fee ledger).

**Expert-band breadth (§1.9)**: **46 corner instances** across all 9 claim-extraction sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model), including 2 `excluded_because:` stubs citing existing §1.8 instances.

**Key consistency fixes applied during generation**: flattened topology to satisfy FK reverse-reachability lint; made `permit_ok` category-conditional (flower/craft vendors need no health permit); redefined `total_fees_collected_cents` to count only {RESERVED, ACTIVE} so the complete+promote compensating invariant holds with zero drift; removed the dead `SUSPENDED` Vendor enum value.

## Step 3: Copy Shared Files — 2026-06-11T22:56:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0302_farmers_market_vendor_booth/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-11T23:00:00.000Z

All structural checks pass. The §4 table has 4 columns and 51 endpoint rows (all endpoints including the test clock), the §5 table has 2 columns and 18 error rows, and the §2.2 verbatim block is intact byte-for-byte. The PRD is complete and all three hard contracts pass.

## Summary

Generated the PRD at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0302_farmers_market_vendor_booth/workspace/PRD.md`.

**Document shape:**
- 5 top-level sections, 256 lines.
- §2: 11 subsections (2.1 RBAC, 2.2 verbatim response envelope, 2.3 pagination, plus 8 domain-specific cross-cutting principles: resource identity/versioning, hierarchical consistency, nested reference resolution, monetary precision, OCC on season allocation, the two market ledgers, permit/category gating, validation ordering).
- §3: 9 lifecycle/process subsections (market+map setup, vendor onboarding, booth competition/waitlist, fee pricing, day operations, weather-cancellation cascade, vouchers, sales reporting+commission, deterministic clock).
- §4: 51-row endpoint table (4 columns). §5: 18-row error table (2 columns).

**Coverage confirmation (all scaffold entities/state-machines/calculations/validations/endpoints/errors/roles covered in prose):**
- **Entities/fields** — Contract 1 PASS: 55/55 entity field names, 5/5 endpoint body params, 12/12 query params, 11/11 path params all present verbatim in backticks. All 11 entities covered.
- **State machines** — all 6 with every transition, precondition, and side-effect cascade in prose; all 25 state values present as exact strings.
- **Calculations** — all 5 (assignment_fee dual-variant, commission provisional/final, market_fee_ledger pinned eval order, voucher_liability_ledger, fee_refund floor proration, waitlist_rank); constants 100/180/150 and bps denominator 10000 embedded; round-half-up and floor rules stated.
- **Validations** — all 13 priorities rendered as explicit ordered chain in §2.11, each matched to its error_id.
- **OCC** — Contract 2 PASS for `season-assignment-stale-booth`: `expected_booth_version` named non-optional, mismatch → `ERR_STALE_BOOTH_VERSION` (412).
- **Endpoints** — all 51 in §4 table; side effects in §3 narrative.
- **Errors** — all 18 error IDs in §2/§3 narrative + §5 table.
- **Roles** — all 3 (`MarketAdmin`, `MarketManager`, `Vendor`) named with identity translated.

**Hard Contracts:** Contract 1 (Field-Name Coverage) PASS — 0 missing. Contract 2 (Rule Coverage) PASS. Contract 3 (§3 Path Purity) PASS — 470 §3 backtick tokens scanned, 0 paths, 0 bare HTTP methods. §2.2 verbatim block confirmed intact. Did not read either withheld design file or any sibling task.

## Step 5: Generate Unit Tests — 2026-06-11T23:20:00.000Z

All complete and validated. Here is the summary.

## Summary

Generated complete test infrastructure for `task_0302_farmers_market_vendor_booth` purely from the four task inputs + the unit-test-generator skill spec.

**Stage 1 — `test_helpers/` (9 files):** `types.py` (12 entity TypedDicts, all `common_fields: true`, plus status/role enums), `api_client.py` (one method per PRD endpoint incl. `_clock/set_current_utc`), `api_errors.py` (18 error IDs with HTTP-status map registered to the framework), `assertions.py`, `factories.py` (input-fields-only payloads with pinned standard policy), `constants.py`, `test_users.py` (opaque MarketAdmin/MarketManager constants + `make_vendor_headers(vendor_id)` for the entity_backed Vendor role), `fixtures.py` (composable onboarding/booth-allocation/attendance/voucher setup helpers using identity threading), and the `__init__.py` barrel.

**Stage 2 — `test_suite/` (conftest + 9 test files), 81 test functions:**
- **Queue A (Difficulty): 36 tests** — all 18 difficulty instances covered, each with ≥2 tests (no shortfall).
- **Queue B (Corner): 45 tests** — 45 of 46 non-stub corner instances covered with ≥1 test each.

**Skips (gaps left as gaps, no placeholders):**
- The 2 `excluded_because:` corner stubs (`weather_cascade_multi_entity_end_to_end`, `permit_gate_violation_to_error_on_assignment`) — not translated; both `difficulty_instance` cross-references resolve to real difficulty instances that own the assertions.
- 1 non-stub corner instance skipped on the PRD-first filter: `Corner/endpoints/list_assignments_filtered_by_booth`. The booth_id list-filter behavior appears only in the §4 routing-table parenthetical, which §4 declares "a routing summary only" and defers query parameters to §3, where no rule-bearing prose describes the filter — fails Coverage condition (documented inline in `test_09`'s module docstring).

**Audits passed:** Every one of the 81 tests carries exactly one `Design:` line copied verbatim from source YAML; all tags resolve to real instances (no orphans/dual/untagged). Every PRD citation has a distinctive ≥8-word substring surviving literal PRD grep. No skip/skipif/xfail anywhere; no scaffold/§/Table leakage. All files byte-compile and all 81 tests collect cleanly.

## Step 6: Generate Implementation — 2026-06-11T23:20:00.000Z

`start.sh` boots cleanly, binds to `0.0.0.0`, runs in the foreground via `exec`, responds within seconds. 404 for nonexistent market with valid auth is correct `ERR_NOT_FOUND`.

## Summary

Built a complete Python + Flask implementation of the **Farmers Market & Vendor Booth Management API** (Expert-difficulty PRD) in `workspace/implementation/`.

### Files (19 total)
- **Launcher/deps**: `start.sh`, `requirements.txt` (flask==3.0.3)
- **Core**: `app.py` (entry + error handlers + blueprint registration), `db.py` (in-memory store + advanceable test clock), `errors.py` (18-code catalog), `response.py` (envelope), `middleware.py` (auth), `common.py` (validation/pagination/rounding/common-fields), `serializers.py`
- **routes/**: `markets.py`, `vendors.py` (vendors+permits+applications), `assignments.py`, `market_days.py`, `check_ins.py`, `sales_reports.py`, `vouchers.py`, `clock.py`, `helpers.py`
- **services/**: `derived.py` (ledgers, permit_ok, no_show_strikes, attendance), `assignment.py` (fee calc, waitlist ranking, reserve/promote/complete/cancel, weather refund), `marketday.py` (open/close/cancel cascades)

### Endpoints: 51 implemented (50 from PRD §4 table + `/_clock/set_current_utc`), all registered and verified via the URL map.

### start.sh contract
Reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` behind `python3 -c "import flask"`, and `exec python3 app.py` runs foreground. Verified: boots ~3s, "Running on all addresses (0.0.0.0)".

### In-memory only, no seeded data
All state lives in plain Python dicts in `db.Store` (one per entity, keyed by id). No SQLite, no JSON files, no disk persistence. No `seed_*()` functions; `app.py` startup only registers routes — store boots empty. Test clock override resets on each boot.

### Key behaviors verified by smoke tests
- Fee calc with size multipliers (SINGLE 100 / DOUBLE 180 / CORNER 150), round_half_up via Decimal; SEASON 75000×150/100=112500, DAILY DOUBLE 5000×180/100=9000.
- Waitlist ranking + auto-promotion on cancel/complete with re-ranking; ledger invariance across complete+promote.
- Dual commission: provisional (gross) vs final (token-reconciled min(gross, reconciled_tokens×face)) — verified 10000 → 600.
- Master weather cascade: DAILY assignments cancelled+full-refunded, booths freed, redemptions REVERSED, batches CLOSED, both ledgers recomputed to 0.
- OCC (expected_booth_version → ERR_STALE_BOOTH_VERSION 412), token overdraw, referential mismatch, permit/category gates, clock-driven permit expiry, full §2.11 validation precedence, envelope shape, pagination defaults.

### One PRD interpretation flagged
`voucher_liability_cents` follows scaffold entity definition literally — `face × (redeemed_tokens − reimbursed_tokens)` — and since the API has no disbursement endpoint, reimbursed is 0, leaving liability positive (matching PRD §3.7's "disbursement lags redemption").

## Step 7: Run Tests and Iterate — 2026-06-12T02:35:15.000Z

All 8 parallel rounds pass cleanly (80/80 each). Exiting with the summary.

## Summary

**Iterations run:** 2 sweeps.
- Sweep 1 confirmed the deterministic failure set: 77/81, the same 4 tests failing in all 8 rounds (`test_clock_sweep_expires_permit_and_demotes_permit_ok`, `test_permit_gate_blocks_assignment_when_permit_lapsed`, `test_permit_gate_pre_empts_category_gate`, `test_season_fee_refund_prorated_by_scheduled_days`). (An earlier accidental run with a malformed `--start-command` missing the `cd` prefix produced a spurious 0/81 "could not be restarted" cascade — the per-test-server restart inside the pytest process resolves `_directory` from `cd dir && cmd`; without the prefix it defaulted to `.` = pytest's cwd (project root), where `start.sh` doesn't exist. Corrected by embedding `cd <impl> && bash start.sh`; that 0/81 was a harness-invocation artifact, not an implementation regression.)
- Sweep 2 after fixes: all 8 rounds 80/80, zero failures, zero errors.

**Tests deleted (PRD-silence / unique-derivability category):**
- `test_season_fee_refund_prorated_by_scheduled_days` (test_07) — BRANCH-ASYMMETRIC SIDE EFFECT / unique-derivability collapse. PRD §3.6 cancels only "every **daily** booth assignment on the day" and applies the refund "when a WEATHER cancellation **cancels an assignment**." The season-prorated formula exists in prose but is tied to the cancellation pathway; a single-day weather cancellation never cancels the season holder (the test itself asserts it stays `RESERVED`). The PRD does not uniquely determine that a non-cancelled season holder receives a prorated refund, so a faithful implementer correctly leaves `fee_refunded_cents == 0`. Scaffold rule that drove generation: `Corner/calculations/season_fee_refund_prorated_by_scheduled_days`.

**Fixes applied to `test_suite/` (STEP 2 — test setup made MORE faithful to PRD):**
- `test_05_gating_and_cross_entity_dependencies.py`, `test_permit_gate_pre_empts_category_gate` and `test_permit_gate_blocks_assignment_when_permit_lapsed`: changed `permit_expiry="2026-05-25"` → `"2026-06-03"`. The old value was before the market's `season_start_date` (2026-06-01), so the PRD §3.2 approval gate correctly rejected with `ERR_NO_HEALTH_PERMIT` (the test's own comment intended "expiry on/after season_start"). The corrected date sits in `[season_start, assignment_day)`, so approval succeeds and the permit still lapses by the 2026-06-06 assignment day, preserving the exact `ERR_PERMIT_NOT_VERIFIED` assertion.
- `test_05_...`, `test_clock_sweep_expires_permit_and_demotes_permit_ok`: the original setup built an application-less PROSPECT vendor, for which PRD §2.10 makes `permit_ok` true regardless of any permit (no approved health-gated category ⇒ no health permit needed). Rebuilt the setup via `create_active_vendor_with_health_permit(..., product_category="DAIRY", permit_expiry="2026-06-30")` so the vendor has an APPROVED health-gated category and `permit_ok` genuinely tracks the VERIFIED HEALTH permit; added a `permit_ok is True` pre-check and fetch the permit via `list_permits`. This makes the test faithfully exercise the verbatim §3.9 rule ("the owning vendor's permit_ok is recomputed to reflect the lost permit") without weakening the `EXPIRED`/`permit_ok is False` assertions. Removed the now-unused `reserve_season_assignment` import from `test_07`.

**Fixes applied to `implementation/`:** None. The implementation was PRD-faithful on all four cases (approval expiry-vs-season_start gate, assignment-window permit gate, clock sweep + permit_ok recompute, and the daily-only weather cascade); the failures were test-artifact bugs and one non-derivable assertion.

## Step 8: Finalize PRD — 2026-06-12T02:39:31.000Z

The edit is in place — a single line revised (line 154), no line count change (both 255 lines). The change is contained within §3.6's existing paragraph (no new sections).

## Summary

**Line counts:** PRD.md = 255 lines; PRD_FINALIZED.md = 255 lines; %-delta = 0% line count change (one paragraph revised in place within §3.6, no lines added/removed).

**Changes (one bullet per change):**
- §3.6 (Weather Cancellation) — revise — Pinned that the day-scoped weather cascade cancels only the day's *daily* booth assignments, so a season holder spanning the window is not cancelled by a single-day weather cancellation, keeps `fee_refunded_cents == 0`, and remains `RESERVED`/`ACTIVE`; the season-prorated share is only computed "if and when a weather cancellation actually cancels that season assignment" — which the daily-only cascade does not do. The prorated formula itself is left verbatim. — `implementation/services/marketday.py:62-66` (cascade filters `assignment_type == "DAILY"`), `implementation/services/assignment.py:194-196,213-220` (`do_cancel(weather=True)` / `compute_weather_refund`).

**Per-edit pre-edit search log:**

Edit 1 — §3.6 weather refund / season holder:
- (a) Subject identified: weather-cancellation fee refund, specifically whether a season holder is refunded (prorated) when a single market day is weather-cancelled, and the triggering condition for the season-prorated share.
- (b) Impl paths enumerated and read:
  - `services/marketday.py:51-88` `do_cancel` — the sole weather-cancellation entry point; its assignment loop filters `assignment_type == "DAILY"` (lines 62-66), so season holders are never cancelled by a day cancellation.
  - `services/assignment.py:183-207` `do_cancel(weather=...)` — sets `fee_refunded_cents` only on the cancelled assignment; reached with `weather=True` only from the daily-only cascade.
  - `services/assignment.py:213-220` `compute_weather_refund` — has a SEASON branch (count non-`CANCELLED` market days, divide, floor) matching the PRD formula, but unreachable in practice (never invoked on a SEASON assignment).
  - `routes/assignments.py:185-195` `cancel_assignment` — manual cancel always passes `weather=False`, so a manually cancelled season assignment also gets no refund (`fee_refunded_cents` default 0).
  - `services/derived.py:72-83` `recompute_market_fees` — confirms a non-cancelled `RESERVED`/`ACTIVE` season holder still contributes its full `fee_charged_cents` (no refund) to the ledger; consistent with `fee_refunded_cents == 0`.
  - §2.7 cross-reference (PRD line 88) — references "the season weather-refund proration… floors its per-day share"; edit deliberately preserves the existing prorated formula so this reference stays valid.
- (c) Wording adjustment: scoped the clarification to the *single-day weather cancellation / daily-only cascade* context and phrased the season branch as "computed if and when a weather cancellation actually cancels that season assignment" rather than claiming a season assignment can never be refunded. This keeps the wording consistent with (i) the present-but-unreached SEASON branch in `compute_weather_refund`, (ii) the manual-cancel path (always `weather=False`), and (iii) the §2.7 floor reference — avoiding a false universal claim while pinning the observed behavior (no season-holder refund on a single weather-cancelled day).

**Items skipped (pure fixture bugs, no PRD silence — verified against impl):**
- test_suite `permit_expiry` date fix (`2026-05-25`→`2026-06-03`): the approval gate (`routes/vendors.py:235`, `expiry_date >= season_start_date`) and the assignment-time window gate (`routes/assignments.py:85-88` + `services/derived.py:42`) both already match PRD §3.2/§2.10/§3.3 verbatim. Old fixture date predated `season_start_date`, a setup error. No PRD edit.
- test_suite clock-sweep fixture rebuild (PROSPECT→ACTIVE w/ APPROVED DAIRY + VERIFIED HEALTH): `routes/clock.py:39-50` matches PRD §3.9 verbatim, and `services/derived.py:30-44` matches §2.10 (no health-gated approved category ⇒ `permit_ok` true regardless of permits). The fixture change made the test exercise the real §3.9 rule. No PRD edit.

## Step 9: Complete PRD — 2026-06-12T02:44:10.000Z

All six edits are in place, each an in-paragraph insert/revision. The diff confirms no new sections, no structural changes. Character delta is +607.

Let me do a final scan for any clear remaining mismatch I might have missed — specifically the redemption reconcile day-status (`ERR_DAY_NOT_OPEN`), which the PRD already pins, and the voucher batch tokens_redeemed cap, already pinned. Those are correct.

Summary block follows.

---

**Summary**

Source: `PRD_FINALIZED.md` (255 lines, 48057 chars) → `PRD_COMPLETED.md` (255 lines, 48664 chars). Char delta: +607. Line count unchanged (all edits are in-paragraph inserts/revisions; no new lines, sections, or paragraphs).

Counts: ambiguity-pins = 5, mismatch-revisions = 1.

Changes:
- §2.8 (Optimistic Concurrency) — insert — ambiguity — pinned that a `SEASON` create omitting `expected_booth_version` is rejected `ERR_INVALID_REQUEST` (PRD never stated the error for a missing required field on the season path) — routes/assignments.py:71-72.
- §3.1 (Standing Up a Market / booth create) — insert — ambiguity — pinned that a negative `grid_row`/`grid_col` is rejected `ERR_INVALID_REQUEST` (PRD said "at least 0" but not the error code; impl uses ERR_INVALID_REQUEST, not ERR_VALIDATION_BOUNDS) — routes/markets.py:92-93.
- §3.1 (set-service) — insert — ambiguity — pinned that a set-service request against a `SEASON_HELD` booth is rejected `ERR_INVALID_STATE` (PRD said "only when not SEASON_HELD" but not the error) — routes/markets.py:157-158.
- §3.3 (Competing for a Booth / daily slot freeness) — insert — ambiguity — pinned that a daily request also requires the booth to not be `OUT_OF_SERVICE` (PRD daily-free rule mentioned only occupying RESERVED/ACTIVE assignments) — services/assignment.py:41.
- §3.8 (Sales Reporting / report birth) — insert — ambiguity — pinned that `reconciled_token_count` is born `null` and only set at reconciliation (PRD stated only `commission_cents` at 0 for the DRAFT report) — routes/sales_reports.py:70.
- §3.8 (final commission / reconcile precondition) — revise — mismatch — PRD required "every voucher redemption ... has itself reached `RECONCILED`"; impl only blocks when a relevant redemption is still `SUBMITTED` (tolerating `REVERSED`) and raises `ERR_INVALID_STATE`. Revised to the impl's exact precondition and pinned the error code — routes/sales_reports.py:161-166.
- §3.9 (Deterministic Time Control) — insert — ambiguity — pinned that `/_clock/set_current_utc` returns `200 OK` with an empty object in `data` (PRD §4 routing table did not classify the clock endpoint's status/body) — routes/clock.py:52.

Notes (behaviors checked and left unchanged because PRD already pins them uniquely): voucher `voucher_liability_cents` with always-zero reimbursement term (§2.9/§3.7 already explain disbursement lags redemption); pagination `limit` clamping (§2.3 "constrained to a minimum/maximum" reads as clamp); the `arrive` RESERVED→ACTIVE cascade is type-agnostic in both PRD §3.5 and impl; season-holder not cancelled by a single-day weather cancel (§3.6 already pinned); redemption reconcile `ERR_DAY_NOT_OPEN` and batch token cap (§3.7 already pinned).
