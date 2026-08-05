# Worklog — task_0886_municipal_cemetery_management

## Step 1: Create task directory — 2026-07-29T11:22:00.000Z

Directory pre-created by orchestrator invocation; created workspace/ subdir. Index/label fixed as task_0886_municipal_cemetery_management (Step 1 scan skipped per instructions).

## Step 2: Generate scaffold — 2026-07-29T11:22:30.000Z

All three files are complete, parse cleanly, pass `scaffold_lint.py` with a clean verdict, and honor the file split (no design keys leaked into SCAFFOLD.yaml; unique instance names across both design files). I did not read any sibling task.

## Summary

Generated the Expert-difficulty scaffold for **Municipal Cemetery Management**:

- `SCAFFOLD.yaml` — §1.0–§1.7 + preamble/concurrency
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8, 18 instances (2 per rule × 9)
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9, 34 instances (32 active + 2 excluded stubs)

### Structural counts
- **11 entities**: Cemetery, Plot, RightHolder, Decedent, Deed, Interment, DisintermentAuthorization, MarkerPermit, Invoice, Payment, CareFundEntry
- **47 endpoints** (flat topology, `/cemetery-mgmt` prefix; includes a `/_clock/set_current_utc` with the mandated 2026-05-01 default)
- **6 state machines** (Plot, Deed, Interment, DisintermentAuthorization, MarkerPermit, Invoice)
- **9 calculations**; **24 errors**; **1 concurrency rule** (OCC on Plot.version); **6 roles** (segregation-of-duties model, 5 opaque operators + entity-backed RightHolder)

### Difficulty mechanisms (all 9 rules, ≥2 differentiated instances each)
- **Dual-variant**: care-fund contribution (NEW_SALE 150000 vs RESALE 100000) on Deed; disinterment settlement (RELOCATION 75000 vs REMOVAL 37500).
- **Combinatorial**: mode (a) tiered interment fee composition (base+depth+day+short-notice=150000); mode (b) round-per-line-then-sum invoice tax (160876 vs the 160875 sum-then-round trap).
- **Non-linear SMs**: cyclic Deed transfer loop; parallel billing×operational axes on Interment.
- **Cascades**: depth-3 deed-surrender → plot reclaim → marker cancel; payment → invoice PAID → deed ISSUED/plot SOLD → care-fund contribution.
- **Priority pairs**: referential-beats-temporal; state-beats-fiscal.
- **Boundaries**: plot capacity `>=`; care-fund zero-floor overdraw.
- **Cross-entity**: Interment←Deed; Interment←Invoice.
- **Temporal overlap**: plot whole-day closed double-booking vs cemetery crew half-open buffered windows.
- **Compensating invariants**: perpetual-care ledger balance (money); plot occupancy count.

## Step 3: Copy INSTRUCTION.md — 2026-07-29T11:22:45.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-29T11:27:00.000Z

Generated workspace/PRD.md (295 lines). 5 top-level sections; §2 has 9 subsections; §3 has 7 subsections. 47 endpoints documented (4-col table). 24 error codes, each also triggered in prose.

Notable rules: dual-variant care-fund (NEW_SALE 15% floor 25000¢ vs RESALE 10% no floor); dual-variant disinterment settlement (RELOCATION 50% vs REMOVAL 25%); tiered interment fee (base+depth+day+short-notice); round-then-sum tax 7.25% per taxable line; parallel Interment operational/billing axes; cyclic deed transfer; disinterment fork-join (health + NoK → approve → execute); OCC deed expected_plot_version → ERR_STALE_VERSION 412; SoD approver≠executor, issuer≠voider; crew whole-day + half-open 60-min buffered windows; append-only care-fund ledger non-negative guard; deed-surrender + disinterment cascades.

Contracts: Field-Name Coverage PASS (77/77), Rule Coverage PASS, §3 Path Purity PASS.

## Step 4.5: Pre-Step-5 undeclared-constant scan — 2026-08-01T00:00:00.000Z

RESUME after weekly-rate-limit kill at Step 4→5 boundary. Scanned SCAFFOLD.yaml §1.4 calculations for named thresholds/windows with no value. ALL constants are declared inline in their calc `constants:` blocks: care-fund (CARE_PCT 0.15, CARE_MIN_CENTS 25000, RESALE_CARE_PCT 0.10); interment fee (BASE_FEE_BY_PLOT_TYPE map, DEPTH_TIER_2 15000, DEPTH_TIER_3PLUS 30000, WEEKEND_SURCHARGE 20000, HOLIDAY_SURCHARGE 35000, SHORT_NOTICE_SURCHARGE 25000, SHORT_NOTICE_DAYS 3, HOLIDAYS list); invoice tax (TAX_RATE 0.0725); disinterment settlement (RELOC_CREDIT_PCT 0.50, REMOVAL_REFUND_PCT 0.25); crew (CREW_BUFFER_MINUTES 60). Capacity uses entity field interment_capacity; depth uses depth_position input. No undeclared test-determinative constant → no SCAFFOLD/PRD patch required. All 3 scaffold YAMLs pass yaml.safe_load.

## Step 5: Generate unit tests — 2026-08-01T00:20:00.000Z

Test files: 9 (test_01–test_09) plus conftest.py, all under test_suite/. Total tests: 70 — all collect cleanly, all files compile.
- Queue A (Difficulty): 38 tests covering all 18 difficulty instances (9 rule_ids × 2), each with ≥2 tests.
- Queue B (Corner): 32 tests covering all 32 non-stub corner instances, each with ≥1 test.
Skipped instances: None. All 18 difficulty + 32 non-stub corner instances passed the PRD-first two-condition filter. The two priority-pair instances are derivable because PRD §2.5 gives an explicit priority ladder ("the first failing rung determines the error returned"). Stubs correctly NOT translated: the 2 excluded_because corner stubs (calculations/care_fund_resale_variant; cross_cutting/disinterment_cascade_decommissions_installed_marker) — both cross-refs resolve to real difficulty instances.
Audits passed: coverage (every difficulty instance ≥2 tests, every non-stub corner ≥1, zero orphan/dual tags); scaffold citation C4 (every docstring ends with one verbatim Design: line); PRD citation C1/C3 (all 92 quoted fragments verify verbatim vs PRD.md).
test_helpers written (9 files): types.py (Decedent/Payment/CareFundEntry carry only id+created_at), api_client.py (53 endpoint methods incl logical-clock setter), api_errors.py (24 error IDs), assertions.py, factories.py, constants.py, test_users.py (opaque roles + make_right_holder_headers + per-id SoD builders), fixtures.py (deed→interment→disinterment→marker pipelines paying invoices via dynamic total_cents lookup), __init__.py.

## Step 6: Generate implementation — 2026-08-01T00:20:30.000Z

Built complete Python + Flask impl in workspace/implementation/. Files: start.sh (reads $PORT default 10000, binds 0.0.0.0, pip-install guarded on `import flask`, exec python3 app.py foreground), app.py (routes/auth/RBAC/validations/SMs/calcs/cascades/envelope), db.py (in-memory dicts empty each boot + logical clock default 2026-05-01T00:00:00Z), requirements.txt (flask).
Endpoints: 47 (all PRD §4). State machines: 6 (Plot, Deed cyclic transfer, Interment parallel operational/billing axes, DisintermentAuthorization fork-join, MarkerPermit, Invoice).
Key correctness: dual-variant care-fund (NEW_SALE floor vs RESALE), round-then-sum per-line tax 7.25%, tiered interment fee (holiday-dominates-weekend + short-notice), half-open crew window w/ 60-min symmetric buffer + per-plot/day double-booking, computed occupancy & perpetual-care balance (conserved, non-negative floor), OCC on deed create (expected_plot_version/ERR_STALE_VERSION), SoD (disinterment approve/execute, invoice void), disinterment settlement variants, all cascades. §2.5 validation ladder enforced (concurrency→state; SoD→fiscal; temporal→fiscal; referential→temporal). Append-only records omit version/updated_at. Input date/datetime echoed verbatim; system timestamps use .000Z. Global request lock for deterministic race tests. Agent self-reported 70/70 under per-test-server (unverified by orchestrator — Step 7 will run the durable 8-round sweep).

## Step 7: Run tests and iterate — 2026-08-01T00:45:00.000Z

CLEAN first-sweep pass. Durable 8-round sweep run via workspace/implementation/sweep.sh (2 waves of 4, script file — no inline pkill). Iterations run: 1 (baseline sweep only). Tests deleted: none. test_helpers/ fixes: none. implementation/ fixes: none (only sweep.sh added as runner).

ORCHESTRATOR INDEPENDENT VERIFICATION (not trusting subagent): re-parsed all 8 results.N.json — each total=70 passed=70, statuses={'passed':70}. Raw grep for skip/xfail as a status value: none. ALL 8 GREEN 70/70, zero skip/xfail = True.

## Step 8: Finalize PRD — 2026-08-01T00:45:30.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits. No PRD_FINALIZED.md produced; Step 9 will start from PRD.md.

## Step 9: Complete PRD — 2026-08-01T00:50:00.000Z

Full PRD-vs-implementation completeness scan → workspace/PRD_COMPLETED.md (started from PRD.md; PRD_FINALIZED.md absent since Step 8 skipped). Source PRD.md 295 lines/41,542 chars → PRD_COMPLETED.md 295 lines/42,241 chars (+699 chars, no line change). Verified NOT byte-identical.
Ambiguity-pins: 3 · Mismatch-revisions: 2.
- §2.6 — insert — ambiguity — pinned interment invoice-line label strings (base, depth_surcharge, day_surcharge, short_notice_surcharge) — app.py:825-826
- §3.2 — insert — ambiguity — pinned deed-surrender refund invoice shape (DEED_SALE subject, holder-billed, one non-taxable refund line of -care_fund_contribution_cents, tax 0, negative total) — app.py:736-737
- §3.4 — revise — mismatch — cancellation: billing_status→VOIDED unconditionally while invoice voided only if still ISSUED (already-PAID invoice on OPENED cancel stays PAID, billing→VOIDED) — app.py:891-897
- §3.5 — revise — mismatch — reordered marker-install gates: ERR_NO_COMPLETED_INTERMENT before ERR_INVOICE_UNPAID — app.py:1132-1141
- §3.7 — insert — ambiguity — pinned invoice list filters (holder_id, subject_id, status) — app.py:1180-1184
Note: §2.5 validation ladder already uniquely resolves open (temporal vs fiscal) and disinterment execute / invoice void (SoD/state vs fiscal) via named error codes — no change needed.

## Pipeline complete — 2026-08-01T00:50:30.000Z

RESUMED from Step 4→5 boundary (weekly-rate-limit kill). Steps 5–9 executed. Final state: 70/70 tests pass across all 8 durable sweep rounds (results.1.json..results.8.json on disk, zero skip/xfail, orchestrator-verified). Step 7 CLEAN (0 fixes) → Step 8 skipped → Step 9 produced PRD_COMPLETED.md (5 edits). Expert task_0886_municipal_cemetery_management GREEN.
