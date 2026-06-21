# Worklog — task_0296_appliance_electronics_trade_in

## Step 1: Create Task Directory — 2026-06-11T08:52:24.000Z

Created `tasks/task_0296_appliance_electronics_trade_in/` with `workspace/` subdirectory. Pre-assigned index 0296 used as instructed (no ./tasks/ scan).

## Step 2: Generate Scaffold (Expert) — 2026-06-11T09:18:37.000Z

Generated the three scaffold artifacts for **task_0296 — Appliance & Electronics Trade-In / Buyback**, targeting the **Expert** difficulty band. All three pass `scaffold_lint.py` cleanly (`VERDICT: clean lint`), and every formula-derived assertion was computed by executing the §1.3 formulas in Python (round_half_up, integer cents) and pinned as literals.

**Output files (all written):**
- `SCAFFOLD.yaml` (717 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1047 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (1287 lines)

**Scale (Expert band):**
- **12 entities**: Catalog, DeviceModel, PromotionCampaign, Customer, TradeIn, Quote, ShippingKit, Inspection, InspectionSlot, Payout, DataWipeCertificate, DispositionRecord
- **38 endpoints** (incl. one `/_clock/set_current_utc` test-driving endpoint), **17 error codes**, **4 roles** (peer_roles: CatalogAdmin/Customer/GradingAgent/FinanceOperator), **2 OCC concurrency rules**
- **Complexity profile**: pricing_engine + workflow_orchestration; layers = dual-variant calc, cascading side effects, rate/threshold triggers, optimistic concurrency; hybrid topology, branching state-machine shape, immediate consistency

**4 state machines**: TradeIn (branching fork at `/inspect` into ACCEPTED/REQUOTED/RECYCLED, plus a cyclic `/reinspect` self-loop), Quote (LOCKED→{HONORED,SUPERSEDED,EXPIRED}), InspectionSlot (BOOKED→RELEASED), Payout (PAID→REVERSED).

**5 calculations**: `graded_value` (multiplier × base − defect deductions, powers-off forces POOR floor + WONT_POWER_ON), `promo_bonus` (round-pct → add-flat → cap, order pinned), `quote_amount`, `inspection_outcome` (recycle-floor then tolerance-band, both inclusive), `wallet_settlement` (store-credit vs external; conserved-quantity invariant).

**Difficulty coverage**: all 9 §0.5 rules × 2 instances = **18 §1.8 instances**, each with a distinct differentiation. The breadth probe adds **34 testable §1.9 corner instances + 6 excluded_because stubs** spanning entities, state machines, calculations, validations, endpoints, errors, RBAC, OCC (cross-cutting), and the consistency model.

**Key design note**: the OCC race was made genuine (passing §1.2.1's serial-observability filter) by adding a `/reinspect` self-loop — a grading agent legitimately supersedes the current re-quote while the TradeIn stays REQUOTED, so a customer's stale-version accept/decline is the only deterministic stale-version path; no forbidden concurrency vocabulary appears anywhere.

## Step 3: Copy Shared Files — 2026-06-11T09:18:56.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-11T09:24:45.000Z

Generated the PRD at `workspace/PRD.md` (277 lines). Difficulty/corner design files withheld (not opened).

**Structure:** 5 top-level sections, 18 subsections, ~278 lines.
- §1 Introduction (3 paragraphs)
- §2 Global Specs (2.1 RBAC, 2.2 fixed response envelope, 2.3 Pagination, 2.4 Validation ordering/precedence, 2.5 Topology & nested-path validation, 2.6 Common resource properties, 2.7 OCC, 2.8 Monetary precision, 2.9 Cascading side effects, 2.10 Logical clock)
- §3 Business Logic, 8 subsections scattered by lifecycle (catalog/price book, promotions, customers/origination, draft→locked quote, ship/receive, inspection+fork+re-quote loop, data-wipe/payout/wallet, inspection-slot capacity)
- §4 Endpoint table (4 columns, all 38 scaffold endpoints)
- §5 Error table (2 columns, all 17 error IDs)

**Hard Contract Reports:** Field coverage PASS (56/56 entity fields, 3/3 endpoint params). Rule coverage PASS (validation ordering spine, 2 OCC rejections, all 4 state machines, all 5 calculations, all 17 error_ids, cascade side-effects, sibling-branch symmetry). Path-purity PASS (§3 contains 0 path/method tokens of 331 backticked). §2.2 envelope byte-identical to canonical source.

## Step 5: Generate Unit Tests — 2026-06-11T09:39:44.000Z

Generated complete test infrastructure under a strict design-index-only contract.

### Stage 1 — `test_helpers/` (9 files)
`types.py`, `api_client.py` (one method per endpoint), `api_errors.py` (17 errors registered), `assertions.py` (per-entity + `find_quote`), `factories.py`, `constants.py` (canonical PHN-1 pricing model + derived cents), `test_users.py` (Customer = `entity_backed` with `make_customer_headers`; other three roles opaque), `fixtures.py` (lifecycle helpers draft→quoted→received→inspected→accepted→paid, plus `setup_requoted_trade_in` returning fresh version for OCC), `__init__.py` barrel export.

### Stage 2 — `test_suite/` (conftest + 9 test files, 70 test functions)
| File | Tests |
|---|---|
| test_01_pricing_calculations | 13 |
| test_02_inspection_fork_and_cascades | 8 |
| test_03_wallet_and_payout_invariants | 6 |
| test_04_validation_precedence_and_dependencies | 8 |
| test_05_temporal_overlaps | 4 |
| test_06_concurrency_occ | 3 |
| test_07_entities_crud | 9 |
| test_08_state_transitions | 10 |
| test_09_validations_rbac_endpoints | 9 |

### Queue counts
- **Queue A (Difficulty):** 36 tests covering all **18** difficulty instances, each with ≥2 tests.
- **Queue B (Corner):** 34 tests covering all **34** non-stub corner instances, each with ≥1 test.

### Instances skipped
None for PRD-coverage failure. All 18 difficulty + 34 corner non-stub instances passed the two-condition filter. The 6 `excluded_because:` corner stubs were left untranslated (correct).

### Audits passed
Every docstring ends with exactly one `Design:` line (70/70); all tags resolve; no dual/untagged tests; all 89 PRD citation segments survive whitespace-normalized grep; no skip/xfail; no scaffold-leakage; all 19 files parse.

**Note from generator:** `quote_expired_beats_invalid_state_on_shipkit` is not actually a precedence conflict in the PRD — on a QUOTED trade-in the state check passes, so only quote-expiry can fail; tested as single-failure scenario (plus mirror happy-path), the PRD-faithful reading.

## Step 6: Generate Implementation — 2026-06-11T09:39:44.000Z

Generated complete Python + Flask REST API at `workspace/implementation/`.

### Files (20 total)
- `start.sh` — foreground launcher; reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` on `import flask` check, `exec`s the server
- `requirements.txt` — Flask 3.0.3
- `app.py`, `db.py` (in-memory dicts, **no seeding** at import), `clock.py` (logical clock), `errors.py`, `response.py`, `middleware.py`, `reqs.py`, `models.py`, `util.py`
- `routes/` — `catalogs.py`, `customers.py`, `tradeins.py`, `clock_route.py`
- `services/` — `calc.py` (pricing), `tradein.py` (lifecycle cascades), `lookups.py`

### Endpoints implemented: 38 (all from PRD §4)
Catalog/config (12), customers (3), trade-in lifecycle (12), child reads + payouts (10), plus `/_clock` test-driving endpoint.

### Key correctness points (smoke-verified)
Response envelope per PRD §2.2; auth/RBAC (4 roles, ownership, validation precedence §2.4); pricing engine (integer cents, round_half_up, condition multiplier → defect deductions → promo bonus round-pct-first/add-flat/cap; non-powering POOR+WONT_POWER_ON override); inspection fork MATCH/REQUOTE/RECYCLE with floor-before-tolerance; OCC `expected_trade_in_version` → ERR_STALE_VERSION (412), `/reinspect` supersede bumps version; wallet ledger invariant (STORE_CREDIT moves wallet+lifetime, ACH/CHECK lifetime only, reversal net-zero); data-wipe gate; promo half-open window overlap; slot 30-min buffered overlap; uniqueness checks; price-lock expiry sweep. Fresh-boot guarantee confirmed (empty store on restart, no seeded entities). All modules pass py_compile.

## Step 7: Run Tests and Iterate — 2026-06-11T09:46:50.000Z

All 8 rounds pass with 70/70. Clean sweep, no flakiness.

**Iterations run:** 2 (initial sweep surfaced 2 deterministic failures; second sweep after the fix was clean 70/70 across all 8 parallel rounds).

**Tests deleted:** None. No test was found to be PRD-silent or non-unique-derivable.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:** Two tests carried fixture/payload bugs (STEP 2 — request inconsistent with PRD precondition). Both supplied `reinspect` findings whose recomputed value resolved to a MATCH, not the downgrade (REQUOTE) outcome that PRD §3.6 requires for a valid re-inspection. A PRD-faithful implementation correctly rejected them with `ERR_INVALID_STATE`.

- `test_suite/test_08_state_transitions.py` — `test_reinspect_supersedes_and_mints_new_requote`: changed the inline reinspect payload from `FAIR + [BATTERY_DEGRADED]` (→ 32000, a MATCH) to `POOR + [BATTERY_DEGRADED, MISSING_PARTS]` (→ 12000), and updated the asserted new-REQUOTE amount from 32000 to 12000.
- `test_suite/test_06_concurrency_occ.py` — `test_accept_requote_stale_version_rejected`: same reinspect-payload correction so the re-inspection succeeds and legitimately bumps `version`, then the stale accept is refused with `ERR_STALE_VERSION`.

**Why the payloads were wrong (PRD §3.6):** the inspection outcome is computed "from the inspected value and the trade-in's locked quote amount." After the first fork the locked quote is the REQUOTE quote at 16000. The old payload's 32000 is ≥ the tolerance minimum (16000 − round(16000×0.15) = 13600), i.e. a MATCH, which §3.6 declares "out of scope for this loop and rejected with `ERR_INVALID_STATE`." No baseline reading (current REQUOTE 16000 or original INITIAL 36000) makes 32000 a downgrade — the scaffold's chosen number was internally inconsistent. The new value 12000 (POOR ×0.35 = 21000, minus 4000 + 5000 = 12000) sits below the 13600 band but above the 5000 recycle floor, so it is a genuine REQUOTE.

**Fixes applied to `implementation/`:** None. The implementation's reinspect outcome logic (`routes/tradeins.py:reinspect`, computing the outcome against the current locked quote amount and rejecting non-REQUOTE outcomes with `ERR_INVALID_STATE`) is PRD-faithful and was left unchanged.

**Final state:** 70/70 passing in all 8 concurrent rounds, deterministic, no flakiness.

## Step 8: Finalize PRD — 2026-06-11T09:49:22.000Z

**Result: zero edits.** PRD_FINALIZED.md is byte-identical to PRD.md (277 lines each, 0% delta; `diff` confirms no difference). No genuine PRD-silence or PRD-mismatch was traceable to the Step 7 diff.

**Why no edits.** The entire `<step_7_diff>` consisted of two `test_suite/` fixture corrections — no implementation fixes, no test deletions, no `test_helpers/` fixes. Both corrected payloads stemmed from a scaffold-internal numeric inconsistency, not a PRD silence. Every behavior the fixes touched is already uniquely determined by existing PRD prose:
- Reinspect outcome baseline ("the trade-in's locked quote amount") pinned by §3.6 (outcome formula) + §2.5 (LOCKED-status quote selection). After the first REQUOTE fork the INITIAL quote is SUPERSEDED and the new REQUOTE quote is LOCKED, so the baseline is unambiguous — matching impl `locked_quote_of` (lookups.py:35-42, called from tradeins.py:284).
- Reinspect validity rule (downgrade-only; MATCH/RECYCLE → `ERR_INVALID_STATE`) pinned verbatim by §3.6; impl matches tradeins.py:289-290.
- New-REQUOTE-at-inspected-value + version-bump-on-reinspect pinned by §3.6 + §2.7; impl matches tradeins.py:308-311.

The scaffold's 32000 payload was a MATCH under both possible baseline readings, confirming a fixture bug, not an interpretation the impl had to choose. Pre-edit search run on the one candidate subject (inspection/reinspection baseline + validity) across calc.py, tradein.py, tradeins.py, lookups.py — all already consistent with PRD prose; no edit warranted.

## Step 9: Complete PRD — 2026-06-11T09:54:51.000Z

**Files:** Source `PRD_FINALIZED.md` (277 lines, 39,550 chars) → `PRD_COMPLETED.md` (277 lines, 41,308 chars). Char delta: **+1,758**. Line count unchanged (all edits in-paragraph; no new paragraphs or sections).

**Counts:** 8 ambiguity-pins, 1 mismatch-revision (the §2.4 state-vs-well-formedness reorder). Total 9 changes.

**Per-change list:**
- §2.3 Pagination — insert — ambiguity — out-of-range `limit`/`offset` silently clamped (limit→[1,100], offset→≥0), not rejected; non-integer is `ERR_INVALID_REQUEST` — `reqs.py:111-122`
- §2.4 Validation Ordering — revise — mismatch — swapped steps 6/7 so **state legality is checked before field-level well-formedness** on transition endpoints; malformed-JSON and missing OCC version still raise `ERR_INVALID_REQUEST` first — `routes/tradeins.py:240-245,273-278,446-449; reqs.py:11-26`
- §2.6 Common Resource Properties — insert — ambiguity — `version` starts at **1** on creation — `models.py:57`
- §2.10 Logical Clock — insert — ambiguity — set-clock response returns adopted instant as single `current_utc` ISO-8601 field in `data` — `routes/clock_route.py:21`
- §3.1 Catalog — insert — ambiguity — catalog `name` uniqueness compared **case-sensitively** (vs. case-insensitive email/model_code/promo_code) — `routes/catalogs.py:50-51`
- §3.2 Promotions — insert — ambiguity — `bonus_cap_cents` is a **required field with no default** — `routes/catalogs.py:195`
- §3.3 Trade-In Origination — insert — ambiguity — on create, acting Customer's `X-User-ID` must equal supplied `customer_id` (`ERR_NOT_OWNER`), checked **after** FK resolution — `routes/tradeins.py:72-77`
- §3.3 Trade-In Origination — insert — ambiguity — `promo_code` resolution **scoped to the device model's own catalog**, matches `code` case-insensitively — `routes/tradeins.py:89-93`
- §3.7 Data-Wipe — revise — ambiguity — recording a data-wipe certificate imposes **no trade-in state precondition** and does not transition the trade-in — `routes/tradeins.py:418-435`

**Left unchanged (already uniquely pinned):** all pricing formulas (condition grading, power-off override, promo round→add→cap order, tolerance band, recycle floor), inspection fork/cascades, wallet/payout/reversal invariants, OCC on accept/decline-requote, half-open promo windows vs. buffered closed slot intervals, RBAC matrix, left-to-right path validation, money-as-integer-cents with round-half-up.

---

## Pipeline complete — 2026-06-11T09:54:51.000Z

All 9 steps finished. Final state: **70/70 tests passing across all 8 concurrent stability rounds**, deterministic. Difficulty: Expert. Artifacts: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design indices), PRD.md → PRD_FINALIZED.md (0 edits) → PRD_COMPLETED.md (9 edits), test_helpers/ + test_suite/ (70 tests), workspace/implementation/ (38 endpoints, Python/Flask, in-memory).
