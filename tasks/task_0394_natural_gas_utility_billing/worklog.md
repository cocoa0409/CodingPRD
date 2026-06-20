# Worklog — task_0394_natural_gas_utility_billing

Scenario: Natural Gas Utility Billing: meter read & therm/CCF conversion, fixed + commodity (PGA) charge, budget/levelized billing, shutoff/reconnect & winter moratorium, meter-set & service order, leak/odor emergency ticket, low-income credit, deposit

Difficulty band: Expert.

## Step 2: Generate Scaffold — 2026-06-17T18:18:06.000Z

Pipeline note: the first scaffold-generator subagent (acdb7414240a5e06a) completed SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml but its connection closed mid-response before writing the third file. SendMessage/agent-resume is unavailable in this environment, so a second focused subagent (ac385411dbbe00b9a) generated only the missing SCAFFOLD_CORNER_DESIGN.yaml, consistent with the two frozen files. All three files are valid YAML with correct top-level keys.

Scaffold counts (Expert band confirmed):
- entities: 13 — RateSchedule, PgaSchedule, Account, PremiseMeter, MeterRead, Bill, BudgetPlan, Payment, ServiceOrder, EmergencyTicket, Deposit, LowIncomeCredit, Clock
- state_machines: 8
- calculations: 11 — consumption_conversion, bill_charges, budget_installment, budget_trueup, low_income_eligibility, low_income_credit, deposit_requirement, shutoff_eligibility, winter_moratorium, ticket_severity, payment_timeliness
- validations: 14
- endpoints: 56
- errors: 24
- roles: 4 (peer_roles)
- complexity_profile: primary=pricing_engine, secondary=compliance_audit; layers=dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency; state_machine_shape=cyclic

SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8): single key scaffold_difficulty_design (list of depth rules).

SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — second-subagent summary (verbatim):
Total: 75 corner instances across all 9 §1.9 sections (70 active test recipes + 5 excluded_because stubs):
| Section | Instances |
| entities | 14 |
| state_machines | 17 (1 stub) |
| calculations | 11 (1 stub) |
| validations | 9 (1 stub) |
| endpoints | 9 |
| errors | 4 (2 stubs) |
| rbac | 5 |
| cross_cutting_complexity_layers | 5 |
| consistency_model | 1 |
Validation: YAML parses; single top-level key confirmed. scaffold_lint.py . -> VERDICT: clean lint (56 endpoints, 13 entities, 70 §1.9 instances, 783 calls scanned, all conform to §1.5; all FKs reverse-reachable). All 5 excluded_because references resolve to real §1.8 instance names; no duplicate names; no name collision with §1.8; zero unbound ${var} placeholders; every expected_account_version is a ${var}; every `as: Account` call carries as_user_id. All references cross-checked against SCAFFOLD.yaml; no new identifiers invented.

## Step 3: Copy Shared Files — 2026-06-17T18:18:37.000Z

Copied ./INSTRUCTION.md -> workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-17T18:26:58.000Z

Pipeline note: first PRD subagent (aa2fdfec539fc6ebb) dropped connection after 5 tool uses before writing the file. Retried with fresh subagent (a5013ee85a6f51f07), which completed successfully.

PRD.md — 299 lines, 45607 bytes. Major sections:
- §1 Introduction (pricing engine + compliance framing, dual billing modes, concurrency/safety motivation)
- §2 Global Specifications — 10 subsections: RBAC (2.1), verbatim Response Structure (2.2), Pagination (2.3), Identity/Timestamps/Versioning (2.4; three common_fields:false event records — MeterRead, Payment, Clock — carry only id/created_at), Nested Addressing (2.5), Monetary Precision/Rounding (2.6), Account OCC (2.7), Logical Clock (2.8), Safety/Moratorium Gates (2.9), Validation Order (2.10)
- §3 Business Logic — 13 subsections (pricing config, account/meter setup, service orders, read→therm conversion, bill drafting/issuing actual-cost + levelized, rebills/overlap, budget billing + true-up, low-income eligibility + per-cycle credit, delinquency/shutoff/moratorium, reconnection/finalization cascades, deposits, payments/on-time standing, emergency tickets)
- §4 Endpoint Definitions — 4-column table, all 58 endpoints
- §5 Error Code Catalogue — 2-column table, all 24 error IDs

Hard Contracts all PASS (Field-Name Coverage 72/72; Rule Coverage incl. OCC + cascades + sibling-branch symmetry; §3 Path Purity 0 violations). Confirmation: neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read; no sibling task opened.

## Step 5: Generate Unit Tests — 2026-06-17T18:44:25.000Z (subagent a94770f9e738753b9)

test_helpers/ (9 files): types.py, api_client.py (one method per endpoint), api_errors.py (24 error IDs + HTTP-status map), assertions.py, factories.py, constants.py, test_users.py (3 opaque roles + entity-backed make_account_headers), fixtures.py (5-tier composite helpers), __init__.py barrel. Verified against real framework API surface.
test_suite/ (conftest + 8 test files).
Counts: 106 test functions = 106 Design tags (one tag per test; no untagged/dual-tagged/orphan).
- Queue A (Difficulty): 36 tests — all 18 difficulty instances covered with >=2 tests each (bill_charges_nonlinear_min_floor_and_credit_branch lifted 1->2 with floor-not-applied counterpart).
- Queue B (Corner): 70 tests — all 70 non-stub instances covered with >=1 test each.
Skipped: 5 — all excluded_because stubs (assertions owned by cited difficulty instances): cancel_shutoff_cancels_auto_created_order_side_effect, variant_selection_levelized_budget_charges_installment, index_rollback_on_meter_read_returns_index_rollback, error_billing_period_overlap_triggerable, error_budget_period_overlap_triggerable. No PRD-first filter skips needed — every non-stub instance had verbatim, uniquely-derivable PRD coverage.
Quality gates: every docstring carries verbatim PRD citation surviving backtick/bold-stripped grep (131/131 after 1 fix); exactly one Design: tag resolving to a real instance; all 17 files compile.

## Step 6: Generate Implementation — 2026-06-17T18:44:25.000Z (subagent a8d8e5fcdd5af1a34)

Python + Flask implementation at workspace/implementation/. 25 files:
- Launcher/deps: start.sh (executable), requirements.txt (flask==3.0.3)
- Core: app.py, db.py (in-memory store), errors.py, response.py (envelope), middleware.py (auth/RBAC)
- Services: services/common.py (validation/rounding/pagination/datetime), services/calc.py (all §1.3 calcs), services/lookup.py, services/serialize.py
- Routes (13 blueprints): clock, rate_schedules, pga_schedules, accounts, meters, meter_reads, bills, payments, budget_plans, deposits, low_income_credits, service_orders, tickets
Storage: strictly in-memory (module-level Store singleton, dicts keyed by id); no SQLite/files/tmp. Only pre-existing record is singleton Clock (system config, not entity data). No entity data seeded/preloaded — fresh boot reports accounts total_count 0.
All 56 method+path endpoints from PRD §4 implemented and registered. start.sh: reads $PORT (default 10000), binds 0.0.0.0, foreground via exec python3 app.py, guards pip install behind import check. Fresh boot HTTP-ready ~1s.
Self smoke-tests passed across envelope, RBAC/ownership, CCF/THERM conversion, bill-charge build, budget/levelized + true-up, OCC 412, deposit lifecycle, shutoff/moratorium gates, SHUTOFF->DISCONNECTED->RECONNECT cycle, finalization cascade, rebill/CORRECTED, overlap checks, GRADE_1 ticket meter-lock, validation ordering (401->403->404->400). One refinement: 0-amount waived deposit collect returns ERR_DEPOSIT_WAIVED_NOT_PAYABLE ahead of generic state check (PRD §3.11).

## Step 7: Run Tests and Iterate — 2026-06-17T18:58:44.000Z (subagent a4a7f352a2fb41b0b)

Outcome: All 8 parallel rounds pass cleanly — 106/106 each. Started at 100/106 (one round dipped to 104) with flaky failures.
Iterations run: 2 sweeps (baseline + final verification) plus an interleaved single-round diagnostic.
Tests deleted: None. Every failing test traced to a PRD rule and was uniquely derivable; all failures were fixture-ordering bugs or an infra boot-latency artifact, never an unfair/scaffold-only assertion.

Fixes to test_suite/ (STEP 2 — fixture/setup made MORE faithful to PRD):
- test_04_shutoff_reconnect_cascades.py — three RECONNECT service orders (_drive_to_reconnect_ready, test_meter_locks_then_returns_to_set_across_cycle, test_reconnect_blocked_without_held_deposit) used scheduled_date=2026-04-03 while clock was 2026-04-01, so immediate dispatch was correctly rejected with ERR_ORDER_NOT_DUE (PRD 3.3). Changed to 2026-04-01 (= clock), passing the scheduled_date>now due check.
- test_05_validations_and_overlaps.py — test_reconnect_with_balance_due_returns_balance_due had same 2026-04-03 vs 2026-04-01 clock mismatch; same fix.
- test_04_shutoff_reconnect_cascades.py — test_deposit_collect_then_refund_conserves_held_cents injected on-time count to 12 BEFORE creating deposit, so PRD 3.11 auto-WAIVED it at amount 0 and collect correctly hit ERR_DEPOSIT_WAIVED_NOT_PAYABLE. Reordered: create+collect deposit first (count 0 -> base 15000 -> HELD), then inject count to 12 to permit refund.

Fixes to implementation/ (root cause of flaky error/BadStatusLine failures):
- app.py — added a startup shim that short-circuits socket.getfqdn() for the bind addresses. Werkzeug calls socket.getfqdn("0.0.0.0") while setting server_name at boot; on this macOS host with an mDNS .local hostname that lookup blocked ~5s on every boot. Under per-test-server isolation × 8 concurrent rounds (~848 reboots), that latency pushed boots past the runner's restart window, producing intermittent "API server could not be restarted" / BadStatusLine errors. Shim cut time-to-port-bind from ~5.13s to ~0.08s with no change to request handling or API behavior.

No PRD-required implementation check weakened, no assertion downgraded, no endpoint/field/seed added. Storage remains in-memory only.

ORCHESTRATOR VERIFICATION: The subagent's final sweep left no results.*.json on disk (its sweep block rm -f's at the start; a trailing diagnostic run had wiped them). Orchestrator re-ran the authoritative 8-round parallel sweep from clean state -> all 8 rounds passed 106/106 (results.1.json..results.8.json now persist in workspace/implementation/). Step 7 had >0 fixes (4 test_suite edits + 1 implementation/ edit, 0 deletions) -> Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-06-17T19:01:53.000Z (subagent ab6c7f36b9de2c5c2)

PRD_FINALIZED.md created as exact copy of PRD.md (299 lines, 0% delta, byte-identical — diff confirms 0 differences). After tracing every <step_7_diff> item to implementation/, NONE revealed a PRD silence or PRD/impl mismatch — all three are pure infra/fixture fixes against behavior the PRD already uniquely determines.
Per-item trace:
- app.py socket.getfqdn shim — pure boot-latency/infra fix; touches no handler/field/error -> no PRD edit.
- test_04/test_05 scheduled_date=2026-04-03 vs clock 2026-04-01 — §3.3 ERR_ORDER_NOT_DUE due-check. Impl rejects strictly-future (scheduled_date>now), allows ==now; PRD §3.3 ("dispatch attempted before the order's scheduled_date has been reached ... is rejected") already fixes the ==-is-reached boundary. Pure fixture bug -> no edit.
- test_04 deposit collect ordering (count=12 -> auto-WAIVE -> ERR_DEPOSIT_WAIVED_NOT_PAYABLE) — §3.11. PRD already states deposit created WAIVED at >=12 consecutive on-time payments AND that collect on amount-0 deposit is rejected with ERR_DEPOSIT_WAIVED_NOT_PAYABLE (unconditional dedicated outcome -> determines precedence). Pure fixture-ordering bug -> no edit.
No-new-mismatch check: N/A (file byte-identical to PRD.md).

## Step 9: Complete PRD — 2026-06-17T19:07:49.000Z (subagent a71317293c6032010)

PRD_COMPLETED.md created from PRD_FINALIZED.md via full PRD-vs-implementation scan. 299 lines (unchanged), 45607 -> 47042 chars (+1435; all in-paragraph, no new sections/lines). Counts: 1 ambiguity-pin + 5 mismatch-revisions.
Per-change:
- §2.3 Pagination — insert — ambiguity — limit<1 clamped up to 1 (not rejected); negative offset clamped to 0; non-integer limit/offset -> ERR_INVALID_REQUEST; created_at ties break by internal creation sequence — services/common.py:227-260.
- §2.4 Identity/Versioning — revise — mismatch — PRD claimed Clock carries id+created_at; impl Clock has neither, only current_utc+heating_season_active. Dropped "Payment can be reversed" clause (no reversal exists) — db.py:38-41, services/serialize.py:87-88.
- §3.1 Pricing Config — revise — mismatch — PRD said schedule `active` flag governs assignability; impl always sets true, no deactivation endpoint, never tests on account open — routes/rate_schedules.py:61, routes/accounts.py:30-53.
- §3.5 Bill charge build — revise — mismatch — PRD said therms_billed = closing read therms_consumed less therms already billed by a prior bill; impl performs no subtraction, always uses closing read's therms_consumed — services/calc.py:100.
- §3.10 Finalization — revise — mismatch — PRD said HELD deposit applied against balance with remainder refunded; impl only flips deposit status to APPLIED (bumps version), no balance_cents mutation/remainder refund; finalization true-up runs unconditionally without ERR_NO_BILLS_TO_TRUE_UP gate and without account-version bump — routes/accounts.py:150-177, services/calc.py:246-254.
- §3.12 Payments — revise — mismatch — PRD said payment may be reversed POSTED->REVERSED; no reversal endpoint exists (§4 has none) -> revised to state reversal is unexposed; pinned on-time increment/reset keys off single most-recently-created allocating POSTED payment; only POSTED payments count toward paid_cents/threshold — routes/payments.py:25-110, 64-84.
Already-pinned (no change): shutoff_eligible = past_due>=7500 AND not moratorium (emergency hold excluded from flag); validation-order priority chain; round-half-up money + one-decimal therms; budget half-open vs billing closed-interval overlap; low-income tier/credit math + post-rounding cap; deposit DELINQUENCY x1.5; ticket severity grading; OCC on issue and budget-plan create.

Note: PRD_COMPLETED.md is a documentation-alignment artifact only — not consumed by the test harness. Implementation and tests are unchanged from the Step 7 green state, so the 8-round 106/106 sweep remains valid.

## PIPELINE COMPLETE — 2026-06-17T19:07:49.000Z
All 8 stability-sweep rounds pass 106/106. Final artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (9 files), test_suite/ (conftest + 8 test files, 106 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (+ results.1..8.json)}.
