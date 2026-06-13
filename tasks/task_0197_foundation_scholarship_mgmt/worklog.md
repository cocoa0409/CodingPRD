# Worklog — task_0197_foundation_scholarship_mgmt

## Step 1: Create task directory — 2026-06-06T13:04:31.000Z

Created `tasks/task_0197_foundation_scholarship_mgmt/` and `tasks/task_0197_foundation_scholarship_mgmt/workspace/` (pre-allocated index per orchestration parameter; Step 1 auto-increment scan skipped). Confirmed `INSTRUCTION.md` present at project root.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-06T13:46:00.000Z

Generated all three scaffold artifacts for **task_0197_foundation_scholarship_mgmt** at **Expert** difficulty, all passing `scaffold_lint.py` clean and an independent grounds/uniqueness verification.

**Files written** (under `tasks/task_0197_foundation_scholarship_mgmt/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (1488 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8 (single key `scaffold_difficulty_design`, 1536 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9 (single key `scaffold_corner_design`, 2849 lines)

**Complexity profile**: primary archetype multi-party negotiation (committee scoring/award) + secondary quota/allocation (endowment commit→disburse); layers = dual-variant calc, cascading side effects, rate/threshold triggers, derived-field reconciliation, optimistic concurrency. **Flat topology** (api_prefix `""`, FKs resolved via filtered-list GETs).

**Scaffold contents**:
- **Entities: 13** — ScholarshipFund, EligibilityCriteria, Applicant, Application, Recommendation (immutable), Transcript (immutable), CommitteeMember, CommitteeAssignment, RubricScore, Award, Disbursement, RenewalReview, StewardshipRecord
- **State machines: 8** — ScholarshipFund (linear), Application (cyclic review↔revision loop), CommitteeAssignment (branching), RubricScore, Award (cyclic ACTIVE↔RENEWAL_PENDING term loop), Disbursement (with compensations), StewardshipRecord, RenewalReview
- **Calculations: 6** — rubric_weighted_value, rubric_total (sum-then-divide-then-round-once), eligibility_match, provisional_award (forward-looking) vs final_award (chronological) dual variant, fund_ledger (conservation invariants), renewal_floor_check
- **Concurrency rules: 1** — OCC on ScholarshipFund.version at award (ERR_STALE_FUND_VERSION, 412)
- **Validations: 21** (priority-ordered); **Endpoints: 58**; **Error catalog: 49**; **Roles: 4** (FoundationAdmin/opaque, Applicant/entity_backed, CommitteeMember/entity_backed, DisbursementOfficer/opaque)

**Design instances**:
- §1.8: **18 instances** = 9 Difficulty Rules × 2 each
- §1.9: **62 instances** (56 active recipes + 6 `excluded_because` stubs); every error code referenced ≥1×; formula asserts pre-computed literals; OCC version inputs use captured `${var}` placeholders.

**Validation**: `scaffold_lint.py` → `VERDICT: clean lint` (858 calls scanned, all FKs reverse-reachable).

## Step 3: Copy shared files — 2026-06-06T13:48:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0197_foundation_scholarship_mgmt/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T13:55:00.000Z

Generated `workspace/PRD.md` — a 297-line prose PRD for the Foundation Scholarship Management API. (Design YAMLs withheld; generated from SCAFFOLD.yaml only.)

### Section structure
- **§1 Introduction** — domain framing (finite endowment, fairness mandate, stewardship obligation, four-role partition).
- **§2 Global Specifications** — 2.1 RBAC (4 roles + identity translation), 2.2 Response Structure, 2.3 Pagination, 2.4 Common Resource Properties + nested-path validation, 2.5 Check-ordering priority, 2.6 Hierarchical Consistency/Cascades, 2.7 Fund Ledger Principle, 2.8 Monetary/GPA Precision, 2.9 Optimistic Concurrency Control.
- **§3 Business Logic** — 8 lifecycle subsections: fund setup, intake, submission/eligibility, committee+scoring, review loop, award decision, stewardship/disbursement, renewal.
- **§4 Endpoint Definitions** — 4-column table, 58 rows.
- **§5 Error Code Catalogue** — 2-column table, 49 rows.

### Coverage confirmation (verified mechanically by generator)
- Entities/fields: all 49 field names + 13 path params present; Recommendation/Transcript correctly `common_fields: false`.
- State machines: all 9 entities' states/transitions/preconditions/cascades expressed in prose (incl. system-automatic transitions).
- Calculations: all 6 rendered as precise prose with constants embedded (weights, quorum 2, floor 60, tiers 90/75, multipliers 1.00/0.80/0.60, GPA factors at 3.50/3.00, max revision 2, max concurrent 3).
- Validations: priority ordering in §2.5; all 21 checks matchable to error_ids.
- Endpoints: all 58 mapped exactly (0 missing, 0 extra).
- Errors: all 49 in §5 + referenced in prose.
- OCC: §2.9 names award write endpoint, `expected_fund_version`, `ERR_STALE_FUND_VERSION` HTTP 412.

### Hard contracts: Contract 1 (Field-Name Coverage) PASS; Contract 2 (Rule Coverage) PASS; Contract 3 (§3 Path Purity) PASS.

## Step 5: Generate unit tests — 2026-06-06T14:20:00.000Z

Generated complete test infrastructure following the design-index-only contract.

**test_helpers/ (Stage 1) — 9 files**: types.py (entity TypedDicts; Recommendation/Transcript carry only id+created_at), api_client.py (one method per endpoint), api_errors.py (ApiErrorId enum + HTTP_STATUS_CODES, 44 errors), assertions.py (per-entity + fund-ledger invariant), factories.py (input-only payload factories), constants.py (thresholds), test_users.py (opaque-role constants + per-instance make_applicant_headers/make_committee_member_headers for the two entity_backed roles), fixtures.py (composite lifecycle helpers), __init__.py.

**test_suite/ (Stage 2) — conftest + 7 test files, 91 tests**:
- Queue A (Difficulty): **36 tests** — all 18 instances covered by ≥2 tests each (each second test asserts a distinct PRD-derivable aspect).
- Queue B (Corner): **55 tests** — all 55 non-stub instances covered by exactly 1 test each.

**Coverage audit (all clean):** Difficulty 18/18 with ≥2 tests; Corner 55/55 non-stub with ≥1 test; 0 broken pointers; 7 `excluded_because:` stubs correctly NOT translated; every test docstring ends with exactly one `Design:` line; no skip/skipif/xfail; all 119 prose PRD citations verified verbatim; full py_compile passes.

**Instances skipped:** none beyond the 7 design-declared corner stubs.

## Step 6: Generate implementation — 2026-06-06T14:20:00.000Z

Generated complete Python + Flask implementation in `workspace/implementation/`.

**Files (11):** start.sh (foreground launcher, guarded pip install + `exec python3 app.py`), requirements.txt (flask==3.0.3), app.py (entry + error handlers + all routes), db.py (in-memory per-entity dicts; id/timestamp/version helpers), errors.py (ApiError + error→HTTP-status catalogue), response.py (success/error envelope meta/response_type/data), middleware.py (auth/role/field validators, pagination parser), services/calc.py (calculations, Decimal/ROUND_HALF_UP), services/ledger.py (fund-ledger + member-count recompute), services/lookups.py (existence lookups + pagination/sort), services/__init__.py.

**Endpoints: 60 implemented** across 13 resource groups.

**State machines / calculations / OCC:** all 8 entity state machines with cyclic flows + cascades; calculations in Decimal/ROUND_HALF_UP (rubric_weighted_value 0.5/0.3/0.2, rubric_total sum→divide→single round, three-criterion eligibility_match with [GPA,RESIDENCY,FIELD] ordering, dual-variant provisional vs final award, integer fund_ledger); OCC on award endpoint only via `expected_fund_version` vs `ScholarshipFund.version` → ERR_STALE_FUND_VERSION (412), checked at priority 20 after ERR_FUND_INSUFFICIENT (priority 19). Validation precedence follows PRD §2.5.

**Contract confirmations:** start.sh reads `$PORT` (default 10000), binds 0.0.0.0, foreground via `exec`; storage in-memory only (plain dicts), no seeding/preload/hardcoded entities, boots empty.

## Step 7: Run tests and iterate — 2026-06-06T14:55:00.000Z

Two consecutive clean 8-round sweeps (16 rounds total, all 90/90). The loop is complete.

**Iterations run:** 4 full 8-round parallel sweeps (1 baseline + 3 after fixes; the final two were both fully clean).

**Initial state:** 91 tests, one deterministic failure + one flaky connection failure.

**Tests deleted (1):**
- `test_terminal_rejected_application_cannot_resubmit` (test_suite/test_02_state_machines.py) — **ERROR PRECEDENCE collapse (STEP 1b unique-derivability)**. The test rejects an application (leaving the fund in `REVIEW`, the application in `REJECTED`) then resubmits, asserting `ERR_APPLICATION_STATE_INVALID`. At that point both gates trip. The PRD contradicts itself on which wins: §2.5 gives an explicit numbered global priority where "Sixth, the parent scholarship fund must be in the lifecycle state the operation requires (`ERR_FUND_NOT_OPEN`...)" precedes "Seventh, the target resource's own state is checked" → yields `ERR_FUND_NOT_OPEN`; whereas §3.3 says "The system first requires that the application is in `DRAFT` (otherwise `ERR_APPLICATION_STATE_INVALID`)" → yields `ERR_APPLICATION_STATE_INVALID`. Two divergent PRD-faithful implementations are demonstrable (the implementation followed the §2.5 global order and returned `ERR_FUND_NOT_OPEN`), so the outcome is not uniquely derivable. Drove by Design rule `Corner/state_machines/terminal_application_rejected_cannot_resubmit`.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
- `app.py` — added an `after_request` hook (`_no_keep_alive`) that sets `Connection: close` on every response. This eliminated the intermittent `requests.exceptions.ConnectionError: BadStatusLine` failures that appeared on random POST endpoints (`/recommendations`, `/begin-awarding`) in 1–2 rounds per sweep — a pooled-socket / connection-reuse race aggravated by the 8× concurrent boot/load of the stability sweep. Forcing fresh sockets per request removed the flakiness. No PRD-traced behavior, endpoint, field, or check was added or weakened.

**Final result:** Two consecutive fully clean 8-round sweeps (16/16 rounds, 90/90 tests each). No remaining failures or flakiness.

## Step 8: Finalize PRD — 2026-06-06T15:05:00.000Z

Produced `workspace/PRD_FINALIZED.md` (Step 7 had 1 deletion + 1 impl fix → skip condition not met → Step 8 ran).

**Line counts:** PRD.md = 297; PRD_FINALIZED.md = 297. Delta: 1 line revised in place, 0 added/removed (one sentence rewritten).

**Changes:**
- §3.3 — revise — Reordered the submit-path precondition prose so gate order is owner → fund-`OPEN` → application-`DRAFT`, matching the §2.5 global ordering (fund state before the application's own state) that the implementation follows; removed the contradictory "first requires that the application is in `DRAFT`" claim and pinned the precedence (a non-`DRAFT` application on a non-`OPEN` fund yields `ERR_FUND_NOT_OPEN`, not `ERR_APPLICATION_STATE_INVALID`) — `implementation/app.py:433-439`.

**Pre-edit search log (Edit 1, §3.3 submit precedence):** subject = relative order of ownership / parent-fund-state / app-own-state gates on submit. Enumerated impl paths: `submit_application` (app.py:427-456, the observable site), `start_review` (466 fund-before-app, consistent), `withdraw_application` (591→593, no fund gate — unaffected), `request_revision`/`finalize_scoring`/`reject_application` (app-state-only, no fund gate), §2.5 prose (owner→fund→target, left verbatim). Wording anchored to "Following the global check ordering of §2.5"; precedence scoped to the submit endpoint only, not generalized, so app-state-only paths are not contradicted.

**Not pinned:** the `Connection: close` after_request hook (app.py:27-35) is pure transport/flakiness mitigation with no PRD-traced behavioral semantics; §2.2 specifies only the JSON envelope body, not connection headers — no edit, per method note.

## Step 9: Complete PRD — 2026-06-06T15:15:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan (always runs).

**Source vs output:** PRD_FINALIZED.md = 297 lines / 44,148 chars; PRD_COMPLETED.md = 297 lines / 45,584 chars. Char delta **+1,436** (4 in-paragraph inserts; no new lines/sections).

**Counts:** 4 ambiguity-pins, 0 mismatch-revisions.

**Per change:**
- §2.4 (path not-found codes) — insert — ambiguity — a non-existent recommendation/transcript targeted by path identifier yields `ERR_APPLICATION_NOT_FOUND` (no dedicated code for these upload artifacts) — `app.py:671, 729`.
- §2.5 (check ordering) — insert — ambiguity — body-field shape validation (presence/type/range/enum) runs up front, before both path-resource existence and body-FK existence, so a malformed body field with an unresolved path/body id returns `ERR_INVALID_REQUEST` — `app.py:536-537`, field-first pattern across create handlers (`app.py:379-384`).
- §3.1 (standing up a fund) — insert — ambiguity — attaching eligibility criteria requires the fund in `DRAFT` (else `ERR_FUND_STATE_INVALID`), check precedes the duplicate-criteria check — `app.py:217-220`.
- §3.2 (application intake) — insert — ambiguity — uploading a recommendation/transcript requires the application in `DRAFT` (else `ERR_APPLICATION_STATE_INVALID`); duplicate-transcript check applied only after that state check — `app.py:640-642, 698-703`.

**Left unchanged:** §3.x workflow prose ordering differences are already pinned by §2.5's global priority rule; all calculations, ledger recompute, OCC guard, round-half-up, GPA boundary inclusivity, cascades, response shapes, and pagination/ordering already matched impl uniquely.

## Pipeline complete — 2026-06-06T15:15:00.000Z

Final verification: all 8 rounds of the last stability sweep report `passed=90 / total=90`. Task artifacts complete: SCAFFOLD (×3), PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (conftest + 7 files, 90 tests after 1 deletion), implementation/ (Python+Flask, in-memory), results.{1..8}.json all green.
