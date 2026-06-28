# Worklog — task_0657_crawlspace_basement_waterproofing

## Step 1: Create task directory — 2026-06-26T14:44:49.395Z

Task directory pre-assigned: `tasks/task_0657_crawlspace_basement_waterproofing` with `workspace/` subdir already present. Auto-index scan skipped per execution parameters. Verified `workspace/` exists and is empty. `INSTRUCTION.md` present at project root.

## Step 2: Generate scaffold — 2026-06-26T15:09:12.760Z

Generated three scaffold artifacts for **task_0657_crawlspace_basement_waterproofing** (Expert difficulty), all passing `scaffold_lint.py` with `VERDICT: clean lint` and verified for internal consistency. Built purely from the scenario description and the skill spec — no sibling tasks consulted.

**Files written:**
- `SCAFFOLD.yaml` (1851 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (842 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (1327 lines)

**Calibration counts (Expert band):**
- Entities: **12** (Job, Homeowner, Inspection, Quote, FinancingApplication, InstallOrder, CrewBooking, Crew, Warranty, ServiceVisit, Claim, FoundationReferral)
- Endpoints: **65** (includes 2 sanctioned `/_seed/*` test-driving fast-forwards and 1 `/_clock`)
- Error codes: **21**
- Calculations: **4** with **6 variants** (≥3 variants required) — quote_pricing, install_reconciliation, assessment_severity, financing_amortization
- State machines: **11** (parallel Job lifecycle × financing dimensions; cyclic Quote revise loop and Claim reopen loop; branching FinancingApplication and InstallOrder rework loop)
- Concurrency rules: 2 (OCC); Roles: 6; Validations: 19 (priority-ordered)

**Design decisions of note:**
- **Archetype:** workflow_orchestration + pricing_engine, flat topology, parallel state-machine shape, peer_roles. Job is a hub with two independent state dimensions (`lifecycle_status` × `financing_status`).
- **Difficulty design:** all 9 rules × exactly 2 instances = 18 instances. Reconciliation literals computed in code (quoted 890775 vs install-final 1020780, variance 130005; financing PRIME/36mo=12404, SUBPRIME/12mo=36672; severity override LOW→MODERATE).
- **Corner design:** 35 active + 4 `excluded_because` stubs across all 9 taxonomy sections.
- **Two interval semantics for Rule 8:** CrewBooking half-open `[start,end)` geometric overlap vs ServiceVisit 7-day min-gap *buffer* between scheduled points (added `ERR_VISIT_TOO_CLOSE`).
- **Concurrency rigor:** reclassified would-be OCC rules through the §1.2.1 serial-observability filter. Kept `warranty-transfer-stale-warranty` (status returns to ACTIVE, holder changes silently).
- **FK reverse-reachability:** set `api_prefix: ""` for the flat scheme; consolidated job-scoped sub-resource list GETs into top-level filtered lists.

## Step 3: Copy shared files — 2026-06-26T15:09:29.658Z

Copied `./INSTRUCTION.md` → `tasks/task_0657_crawlspace_basement_waterproofing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T15:14:52.889Z

Generated `workspace/PRD.md` from `SCAFFOLD.yaml`. **316 lines.**

**Section structure:**
- §1. Introduction (2 paragraphs)
- §2. Global Specifications (10 subsections): 2.1 RBAC, 2.2 Response Structure (fixed verbatim block), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning, 2.5 Logical Clock, 2.6 Nested Path Resolution, 2.7 Validation Ordering, 2.8 OCC, 2.9 Monetary Precision/Rounding, 2.10 Cascading State Consistency
- §3. Business Logic & Workflows (12 subsections by entity-lifecycle/business-process): Job setup & dual tracks, Inspection/severity, Foundation referrals, Quoting/pricing/revision, Acceptance, Financing, Install scheduling/run/reconciliation, Crews & bookings, Warranty issuance/transfer/lapse, Service visits, Claims/reopen, Job closure
- §4. Endpoint Definitions (4-column table, all 66 endpoints)
- §5. Error Code Catalogue (2-column table, all 21 error IDs)

**Hard Contracts:** Contract 1 (field coverage 76/76) PASS; Contract 2 (rule coverage — validations, OCC, state machines, calculations, errors, cascades, sibling symmetry) PASS; Contract 3 (path purity in §3) PASS. §2.2 verbatim block confirmed byte-for-byte.

**Confirmation:** the two design YAMLs (DIFFICULTY, CORNER) were NOT read.

## Step 5: Generate unit tests — 2026-06-26T15:27:40.368Z

Generated complete test infrastructure under the design-index-only contract.

**test_helpers/ (9 files):** types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py, __init__.py. Homeowner carries only id/created_at (common_fields:false); all others carry created_at/updated_at/version. `make_homeowner_headers(id)` builder for the lone entity-backed role.

**test_suite/ (conftest + 8 test files, 71 tests):** organized by domain concern.

**Coverage:**
- Queue A (Difficulty): **18/18 instances translated, 0 skipped** (37 difficulty-tagged tests, ≥2 per instance).
- Queue B (Corner): **35/35 non-stub instances translated, 0 skipped** (34 corner-tagged tests). The 4 `excluded_because:` stubs (ERR_CREW_DOUBLE_BOOKED, ERR_VISIT_TOO_CLOSE, ERR_FINANCING_UNRESOLVED, ERR_CREW_CAPACITY_EXCEEDED) correctly NOT translated.

**Verification:** all 71 tests collect cleanly; every docstring ends with exactly one resolving `Design:` line; verbatim PRD-span grep passed; no skip/xfail; no scaffold leakage.

**Note on translated assertion:** corner instance `list_jobs_pagination_envelope` asserts pagination in the envelope `meta` object (PRD §2.3 correct location) rather than `data.total_count`.

## Step 6: Generate implementation — 2026-06-26T15:27:40.368Z

Built complete Python + Flask implementation in `workspace/implementation/` (28 files).

**Files:** start.sh, requirements.txt (Flask 3.0.3), app.py, db.py, errors.py, response.py, middleware.py, helpers.py, clock.py, serializers.py; services/ (calculations.py, factory.py, derived.py); routes/ (13 blueprints: admin, homeowners, crews, jobs, inspections, quotes, financing, install_orders, crew_bookings, warranties, service_visits, claims, foundation_referrals).

**Endpoints:** 65 route handlers covering every row of PRD §4 / SCAFFOLD §1.5.

**State machines & calculations:** parallel Job dimensions (lifecycle_status × financing_status) tracked independently; cyclic/branching machines (Quote revision, Claim reopen, InstallOrder PASS/FAIL rework, Warranty transfer-settle). Calculations use Decimal + ROUND_HALF_UP in pinned order. Validation ordering per PRD §2.7. All structural names read verbatim from PRD.

**start.sh contract confirmed:** reads $PORT (default 10000), binds 0.0.0.0 (verified via ss), runs foreground via `exec python3 app.py`, pip install guarded behind flask import check, in-memory only (module-level dicts, no SQLite/JSON/tmp), no startup seeding (fresh boot total_count=0).

## Step 7: Run tests and iterate — 2026-06-26T15:53:29.228Z

**Result: GREEN — all 8 parallel rounds 71/71 (independently re-verified by orchestrator after the fix subagent exited; results.1..8.json on disk all passed==total==71, failed==0).**

**Iterations run:** 4 sweeps (initial diagnosis + 3 verification sweeps). Clean 8-round parallel sweep achieved on the final run.

**Tests deleted:** None. Every failure traced to a fixable test-helper/test-suite bug or environmental flakiness, not to PRD-silent or non-uniquely-derivable assertions.

**Fixes applied to test_helpers/:**
- `test_helpers/fixtures.py` — `setup_passed_install_order`: changed the `inspect_pass_install_order` call from the `SCH` (Scheduler) role to `INS` (Inspector). PRD §3.7 / RBAC table makes inspect-pass an Inspector-only operation; the Scheduler header caused a PRD-faithful `ERR_FORBIDDEN_ROLE` 403 during setup, failing 5 "complete"/reconciliation tests depending on this helper.

**Fixes applied to test_suite/:**
- `test_suite/test_05_install_and_scheduling.py` — `test_complete_response_carries_reconciled_total_immediately`: same role bug inline; changed `inspect_pass_install_order(io_id, SCH)` → `INS`.

**Fixes applied to implementation/:**
- `workspace/implementation/start.sh` — moved the dependency check behind a `/tmp` sentinel so the per-test reboot hot path is a bare `exec python3 app.py` (no extra interpreter spawn per restart). Remaining failures were "could not be restarted"/`ConnectionResetError(104)` boot flakes under 8× concurrent per-test-server reboots saturating the host; cutting per-reboot CPU churn eliminated the flakiness. No application logic/state change; storage remains in-memory-only, sentinel lives in `/tmp`.

**Key finding:** The implementation was already PRD-faithful (inspect-pass→Inspector, complete→Scheduler correctly enforced in `routes/install_orders.py`). The only logic-level failures were test-side role mismatches; the rest was host-saturation boot flakiness resolved by trimming start.sh overhead.

**Step 8 trigger:** Step 7 had >0 fixes (test_helpers/, test_suite/, implementation/start.sh) → Step 8 will run.

## Step 8: Finalize PRD — 2026-06-26T15:55:01.289Z

**PRD.md vs PRD_FINALIZED.md: 316 vs 316 lines, 0% delta — verbatim copy, 0 edits.** (Verified by orchestrator: `diff` shows files identical.)

All three Step 7 diff items are pure fixture/environment bugs revealing no PRD silence or mismatch:
1. `test_helpers/fixtures.py` SCH→INS for inspect-pass — pure fixture bug; PRD §3.7 + RBAC table (line 262) already pin inspect-pass→Inspector, impl faithful (`routes/install_orders.py:93`).
2. `test_suite/test_05` same inline SCH→INS — same root cause.
3. `implementation/start.sh` /tmp sentinel — pure boot/perf fix, no logic/state change.

Verified install-order route authorizations all match PRD §3.7 prose + RBAC table (dispatch/start/complete/cancel→Scheduler, inspect-pass/inspect-fail→Inspector). No manufactured edits.

## Step 9: Complete PRD — 2026-06-26T16:01:45.349Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`. **TERMINATION SIGNAL ON DISK.**

**Counts:** source PRD_FINALIZED.md 316 lines / 47,355 chars → PRD_COMPLETED.md 316 lines / 49,323 chars (+1,968 chars; no line-count change — all edits in-paragraph). **9 ambiguity-pins, 1 mismatch-revision** (10 paragraphs touched).

**Changes:**
- §3.2 Inspection — insert — ambiguity — moisture_pct out of 0–100 and negative structural_findings_count → ERR_VALIDATION — routes/inspections.py:26-29
- §3.3 Foundation Referrals — insert — ambiguity — outcome literals exactly ACCEPT/REJECT; else ERR_INVALID_REQUEST — routes/foundation_referrals.py:14,85
- §3.4 Quoting (scope) — insert — ambiguity — negative drain_linear_ft → ERR_VALIDATION; non-enum discount_code → ERR_INVALID_REQUEST — routes/quotes.py:28-30, helpers.py:61-67
- §3.4 Quoting (decline/expire) — revise — mismatch — removed false "or read" auto-expiry claim (GET returns sent quote unchanged); decline imposes no job-state check; expire-before-expires_at/not-SENT → ERR_INVALID_STATE — routes/quotes.py:161-187
- §3.6 Financing (submit) — insert — ambiguity — amount_financed_cents taken from body quote_id's total_cents, no requirement it equal Job's accepted_quote_id — routes/financing.py:26,41
- §3.6 Financing (decide) — insert — ambiguity — decision literals exactly APPROVE/DECLINE; else ERR_INVALID_REQUEST — routes/financing.py:15,90
- §3.7 Install completion — insert — ambiguity — negative actual_drain_linear_ft → ERR_VALIDATION — routes/install_orders.py:120-122
- §3.8 Crews/bookings — insert — ambiguity — daily_capacity < 1 → ERR_VALIDATION; active flag never enforced as booking precondition — routes/crews.py:25-26, routes/crew_bookings.py
- §3.8 Booking confirm — insert — ambiguity — calendar day for capacity = UTC date of window_start, counting other CONFIRMED bookings sharing that date — routes/crew_bookings.py:93-104
- §3.9 Warranty issuance & lapse — insert — ambiguity — "plus one year" = calendar-year add (Feb 29→Feb 28 clamp); lapse → ERR_INVALID_STATE when not ACTIVE or clock before threshold; lapse only via explicit op — helpers.py:18-24, routes/jobs.py:146, routes/warranties.py:99-105
- §3.10 Annual service completion — insert — ambiguity — last_service_at/next_service_due use logical clock at completion (not scheduled_for); calendar-year reset — routes/service_visits.py:104-108

**Verified already-consistent (no change):** validation precedence (§2.7) state→OCC→expiry on accept; sibling-quote decline scoped to SENT; install-order quote_id pinned to Job's accepted_quote_id; deny only from OPEN; warranty TRANSFERRED settling back to ACTIVE; service-visit 7-day spacing as absolute time diff.

---

## PIPELINE COMPLETE

All 9 steps executed end to end. Final state: **71/71 tests passing across all 8 parallel stability rounds.** Termination artifact `workspace/PRD_COMPLETED.md` present on disk.
