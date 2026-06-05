# Worklog — task_0074_brokerage_options_approval

## Step 1: Create task directory — 2026-05-31T16:46:29.000Z

Created `tasks/task_0074_brokerage_options_approval/` with `workspace/` subdirectory. Output path pre-allocated; no index scanning performed.

## Step 2: Generate scaffold (Expert difficulty) — 2026-05-31T17:02:36.000Z

All `excluded_because` references resolve to existing difficulty instance names. The scaffold is complete and consistent.

Generated all three scaffold artifacts for **task_0074_brokerage_options_approval** (Expert difficulty band). `scaffold_lint.py` reports **VERDICT: clean lint**.

**Complexity profile**: primary archetype `compliance_audit`, secondary `ledger_reconciliation`; flat entity topology; branching state machines; segregation-of-duties role model; layers = dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency.

**Entities (7)**: `Account` (KYC/W-9, options_level 0-4, margin_type CASH/REG_T/PMA, computed buying_power/equity/maintenance_margin/day_trade_count/pdt_flagged), `OptionsApproval`, `MarginUpgrade` (OCC parent = Account), `Position`, `Order` (LIMIT/STOP/TAKE_PROFIT), `DayTrade` (append-only PDT log, common_fields:false), `AcatTransfer` (IN/OUT). 39 endpoints, 24 error codes, 3 roles (AccountHolder, ComplianceOfficer, Custodian — all opaque).

**State machines (6)**: Account (compound, PENDING_KYC→ACTIVE↔RESTRICTED→CLOSED with PDT auto-restrict cascade), OptionsApproval & MarginUpgrade (branching approve/reject), Order (accept→partial/full fill→fill, cancel/reject), AcatTransfer (validate→settle / reject / cancel), Position (open→close). One concurrency rule: OCC on Account.version at margin-upgrade approval (412).

**Calculations (6)**: `buying_power` (dual-variant Reg T 2×-excess vs PMA 15%-risk-based vs CASH), `maintenance_margin_requirement` (round-per-position-then-sum), `pattern_day_trader_status` (4-day-trade / trailing-5-day window / $25k equity threshold), `order_notional` (order-type leg selection + option ×100 multiplier + SELL-to-close dual interpretation), `options_suitability_gate` (per-level combined-wealth + experience-rank thresholds), `trigger_eligibility` (per-order-type required prices).

**Difficulty design**: 18 instances = 2 per each of the 9 rule_ids. All formula-derived asserts pre-computed to literals.

**Corner design**: 40 instances (37 with executable test recipes + 3 `excluded_because` stubs pointing to §1.8).

**Notable design decisions**: api_prefix set to root (`""`) for the flat peer-collection topology so FK reverse-reachability resolves via filtered-list GETs; one test-driving endpoint `POST /_day-trades/seed` added (last-resort priority-ladder rung) because the accept-time PDT block makes a flagged+RESTRICTED-under-$25k state unreachable through composed business endpoints.

## Step 3: Copy INSTRUCTION.md — 2026-05-31T17:02:39.000Z

Copied root `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-31T17:07:13.000Z

Generated `workspace/PRD.md` from the Expert-band scaffold. ~284 lines; 5 top-level sections, 20 subsections.

**Coverage:** Entities (7): Account, OptionsApproval, MarginUpgrade, Position, Order, DayTrade (append-only id+created_at only), AcatTransfer. State machines (6) all transitions with preconditions/error IDs/side-effects. Calculations (6): dual-variant buying_power, maintenance_margin, pattern_day_trader_status, order_notional, options_suitability_gate, trigger_eligibility — constants embedded as prose. Endpoints (40) in §4 table incl. `/_day-trades/seed`. Errors (24) in §5 + narrative. RBAC: 3 opaque roles, SoD + ownership via account_holder_user_id.

**Hard contracts:** Contract 1 (Field-Name Coverage) 45/45 PASS; Contract 2 (Rule Coverage) OCC/transitions/calcs/priority orderings/cascades PASS; Contract 3 (§3 Path Purity) 0 violations PASS.

## Step 5: Generate unit tests — 2026-05-31T17:20:05.000Z

**Stage 1 — test_helpers/ (9 files):** types.py (DayTrade omits version/updated_at), api_client.py (39 endpoints incl /_day-trades/seed), api_errors.py (24-error enum + status map), assertions.py, factories.py, constants.py, test_users.py (3 opaque roles), fixtures.py (composite setup: activation, options grants, margin upgrades w/ OCC version, position/order lifecycle, day-trade accumulation, ACAT settle), __init__.py.

**Stage 2 — test_suite/ (conftest + 6 files), 73 test functions:** test_01 buying power/margin (11), test_02 order notional/maintenance (10), test_03 options/margin workflows (10), test_04 account cascades (9), test_05 PDT/day trades (8), test_06 lifecycle/validation/RBAC/listing (25).

**Coverage:** Queue A (Difficulty) 36 tests covering all 18 instances ≥2 each; Queue B (Corner) 37 tests covering all 37 non-stub instances ≥1 each. Every function carries exactly one Design: tag resolving to a real instance.

**Skipped:** None on correctness grounds. 3 `excluded_because:` corner stubs correctly not translated (assertions owned by cited difficulty instances).

**PRD-faithfulness notes:** order_accept_requires_account_active creates DRAFT order after restriction; citation docstrings verified verbatim incl em-dashes.

## Step 6: Generate implementation — 2026-05-31T17:20:05.000Z

Built Python + Flask in-memory implementation at `workspace/implementation/`.

**Source files (3):** app.py (single-file: envelope, auth/RBAC, error handling, 7 entities, computed-field engine, state machines, calculations, endpoints), requirements.txt (Flask 3.0.3), start.sh (foreground `exec python3 app.py`, reads $PORT default 10000, binds 0.0.0.0).

**Endpoint count: 38** — Account (6), OptionsApproval (6), MarginUpgrade (6), Position (4), Order (7), DayTrade (3 incl /_day-trades/seed), AcatTransfer (8).

**Notable decisions:** pure in-memory dicts, no seeding, empty on boot, monotonic _seq tiebreaker for created_at sort. Money = integer cents, exact integer floor (mv*25//100, equity*100//15), per-position floor-then-sum. Computed fields recomputed on read + eagerly on mutation. Validation order: auth → role → existence → state → business. SoD checked before suitability gate and before OCC version check. PDT: accept-time preventive block (ERR_PDT_RULE_BLOCK) + fill/seed-time cascade to RESTRICTED with equity call on restore (ERR_PDT_EQUITY_CALL); /_day-trades/seed produces unreachable flagged+restricted state. Restrict cascade cancels working orders + rejects pending options approvals (rejection_reason=ACCOUNT_RESTRICTED), bumps child version/timestamp.

## Step 7: Test and iterate to green — 2026-05-31T17:39:50.000Z

Clean 8-round parallel sweep: all 8 rounds passed 73/73, zero failures.

**Iterations run:** 2 sweeps (initial diagnostic + final verification), with intermediate single-round and boot-latency profiling to isolate the flakiness root cause.

**Tests deleted:** None. Every assertion traced to verbatim PRD prose and was uniquely derivable.

**Fixes applied to test_suite/** (test bugs per STEP 2 — fixtures issuing requests inconsistent with PRD's declared status-code convention):
- `test_suite/test_03_options_and_margin_workflows.py`, `test_margin_upgrade_noop_same_type_rejected` and `test_pma_upgrade_below_equity_minimum_rejected`: `create_margin_upgrade` calls used `validate_success(...)` with default `expected_status=200`, but PRD line 212 states "Operations that create a new, stand-alone resource return a `201 Created`." Added `expected_status=201` to both. (Implementation was already correct, returning 201.)

**Fixes applied to implementation/:**
- `workspace/implementation/app.py`, `create_order()` + new `require_enum()` helper: `order_type` was extracted via `require_field` with no enum check, so PRD-invalid value `"MARKET"` was accepted (201) instead of rejected. PRD §3.5 line 168 enumerates `order_type` as exactly `LIMIT`/`STOP`/`TAKE_PROFIT`, §2.6 maps invalid input to `ERR_VALIDATION` (422). Added enum validation.
- `workspace/implementation/start.sh`: changed unconditional `pip install` on every restart to one-time install guarded by `.deps_installed` marker (no behavioral change; in-memory DB still resets each boot).

**Key finding — dominant flakiness ("could not be restarted"):** all 30 non-assertion failures were server boot timeouts, not logic bugs. Root cause: `socket.getfqdn("0.0.0.0")` stalls ~5s on this host; Werkzeug's dev server calls it at startup. The runner ships the fix: `_dnsboot/sitecustomize.py` shim injected via `lifecycle.py` PYTHONPATH that fast-paths `getfqdn` for unspecified addresses. Boot dropped 6.8s → 0.09s (75x); final 8-round sweep clean 73/73 × 8. No application code change needed for the DNS stall — handled environment-side.

## Step 8: Finalize PRD — 2026-05-31T17:41:27.000Z

Produced `workspace/PRD_FINALIZED.md`. Line counts: PRD.md 283, PRD_FINALIZED.md 283, 0% delta (single inline edit).

**Changes (1):**
- §3.5 (line 168) — revise — Pinned that a present-but-out-of-enum `order_type` value at order creation is rejected with `ERR_VALIDATION`; PRD previously only listed allowed values without stating rejection behavior — `implementation/app.py:968` (`require_enum`).

**Step 7 diff items considered:** test_suite 201-vs-200 fixes → no PRD edit (pure fixture bugs; PRD line 212 + impl already correct). start.sh guard → no PRD edit (no behavioral change). create_order enum → PRD edit applied (genuine silence).

**NO-NEW-MISMATCH:** scoped clause to `order_type` alone, since only `order_type` is enum-validated at create; sibling fields (instrument_type, side, requested_margin_type, direction, investment_experience, requested_level) use plain require_field (absence-only), so a broader phrasing would have introduced a new mismatch.

## Step 9: Complete PRD — 2026-05-31T17:44:22.000Z

Produced `workspace/PRD_COMPLETED.md` via 5 minimal in-paragraph edits. Source PRD_FINALIZED.md 283 lines/39,715 chars → PRD_COMPLETED.md 283 lines/40,499 chars (+784 chars). Ambiguity-pins: 3, mismatch-revisions: 2.

**Changes:**
- §3.5 (Order creation) — revise — mismatch — PRD said order `quantity` "must be greater than zero"; impl only checks presence, no positivity guard. Revised to presence-only — app.py:969.
- §3.10 (ACAT reject) — revise — mismatch — PRD pinned `reject_code` to a 3-value set; impl only rejects empty/falsy and stores any non-empty string. Revised to "non-empty ... not validated against that set" — app.py:1301-1305.
- §3.9 (Day-trade seed) — insert — ambiguity — pinned required inputs (account_id/trade_date/integer count), optional symbol default `SEED`, null closing_order_id, 201 with recomputed Account — app.py:1154-1178.
- §3.8 (Order notional) — insert — ambiguity — pinned notional_cents null on DRAFT, computed/frozen at accept, never recomputed by fills — app.py:972,1071.
- §4 (GET /accounts) — revise — ambiguity — pinned filter param name `account_holder_user_id` — app.py:562-564.

**Confirmed already-pinned (no change):** PDT rolling window, CASH/REG_T/PMA buying-power formulas, per-position floored maintenance, suitability thresholds/experience ranks, version-increment cascades, order-accept validation precedence, order_type-only enum validation asymmetry.

---

## Pipeline complete — all 9 steps finished. Final state: 73/73 tests passing across 8 parallel rounds.
