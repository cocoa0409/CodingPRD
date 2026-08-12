# Worklog — task_1154_rollover_plan_plan_transfer_processing

## Step 1: Create Task Directory — 2026-08-11T03:27:00.000Z

Task directory `tasks/task_1154_rollover_plan_plan_transfer_processing/` and its `workspace/` subdirectory were pre-assigned and already exist (index 1154 assigned by the pipeline invoker; Step 1 auto-index scan skipped per instructions). Verified both directories exist on disk.

## Step 2: Generate Scaffold — 2026-08-11T04:29:00.000Z

Scaffold generation complete. All three artifacts exist, parse as YAML, and pass `scaffold_lint.py` clean.

## Output files (all in `/home/ubuntu/github/CodingPRD/tasks/task_1154_rollover_plan_plan_transfer_processing/`)

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 1035 | §1.0–§1.7 only (no difficulty/corner keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 897 | single top key `scaffold_difficulty_design:` (§1.8) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 1124 | single top key `scaffold_corner_design:` (§1.9) |

## Counts
- **Entities: 13** (Plan, PlanFreezeWindow, Participant, Account, MoneySourceBalance, Loan, RolloverCase, RequiredDocument, SourcePlanVerification, Disbursement, Redeposit, FollowUpNotice, TaxForm — flat topology with FK links, self-referential `TaxForm.supersedes_id`, polymorphic receiving destination)
- **Endpoints: 55** (incl. test-driving `POST /_clock/set_current_utc` with pinned startup default `2026-05-01T00:00:00Z`)
- **Error catalog: 44** — every error referenced by §1.2/§1.4 and exercised by at least one §1.8/§1.9 instance
- 9 state machines (cycles on RolloverCase, RequiredDocument, Disbursement; guarded transitions), 9 calculations, 9 ordered validation priorities, 5 roles (segregation-of-duties model: approver cannot move money), 2 OCC concurrency rules (`case-amend-stale-version`, `taxform-correction-stale-version`)
- **§1.8 difficulty instances: 23** (dual_variant_calc 2, combinatorial_formula 3 [modes a/b/c], non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2)
- **§1.9 corner instances: 68** (45 full recipes + 23 `excluded_because` stubs, all stub refs resolve to §1.8 names)

## Difficulty-handling ("harder than expert")
Went beyond the Expert band on the dimensions §0.4 says actually matter, not just volume: dual-variant tax math (provisional vs corrected 1099-R; standard vs qualified loan-offset windows), pinned rounding order with a falsifiable 1-cent divergence (floor+largest-remainder 740,741/111,111/92,593/55,555 vs naive half-up sum 1,000,001), pinned evaluation order for the withholding chain, depth-3 cascades (plan freeze → case suspend → disbursement cancel → balance restoration; redeposit credit → case completion → notice/tax-form updates), month-precision age boundary (714 vs 713 months), inclusive day-60 deadline, two disjoint validation-priority pairs, and two OCC-guarded write paths. All formula-derived asserts are literals computed by executing the formulas (verified via Python).

## Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(829 design-file calls scanned; 10 initial `FK_REVERSE_UNREACHABLE` violations were fixed by renaming sub-resource templates to the literal `{id}` placeholder the linter's parent-prefix check requires.)

One design note: mid-generation I restructured disbursement issuance into assemble (`issue-disbursement` → PENDING) + money-movement (`disbursements/{id}/issue`) steps — this makes the freeze cascade genuinely depth-3 and gives the cancel/compensation invariant an observable pre-money state.

## Step 3: Copy Shared Files — 2026-08-11T04:30:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1154_rollover_plan_plan_transfer_processing/workspace/INSTRUCTION.md` (1424 bytes; verified on disk).

## Step 4: Generate PRD — 2026-08-11T04:38:00.000Z

The PRD is complete, ends at §5 with no audit footer, and all three hard contracts pass. The output file is verified on disk at 372 lines.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1154_rollover_plan_plan_transfer_processing/workspace/PRD.md` — 372 lines.

**Section structure and scaffold coverage:**

- **§1 Introduction** (3 paragraphs) — covers scaffold `scenario` + `complexity_profile` (§1.8 profile concepts: compliance/ledger archetypes, OCC, cascading side effects, logical clock).
- **§2 Global Specifications** (10 subsections) — covers §1.7 roles/identity (§2.1, including all five roles' `identity:` translations), §1.0 response envelope verbatim (§2.2), §1.0 pagination defaults (§2.3), logical clock (§2.4), common resource properties from entities with `common_fields: true` (§2.5), segregation of duties from §1.4 priority-5 (§2.6), §1.3 precision rules (§2.7), §1.2.1 concurrency_rules OCC (§2.8), §1.4 validation priority ordering + nested-resource left-to-right resolution (§2.9), and PlanFreezeWindow rules from §1.4 priority-7 (§2.10).
- **§3 Business Logic & Workflows** (11 subsections, entity-lifecycle strategy) — covers §1.1 entities, §1.2 state machines (all transitions, preconditions with error IDs, side effects, cascades), §1.3 calculation rules (eligibility_determination, vested_balance, source_allocation, indirect_withholding, tax_form_amounts, sixty_day_window, loan_offset_window, required_document_rules, redeposit_completion — all rendered as precise prose, no pseudocode), and §1.4 validation conditions paired with their error IDs near the workflows they guard.
- **§4 Endpoint Definitions** — 4-column table (Method/Path/Description/Authorized Roles) covering all 53 endpoints from §1.5.
- **§5 Error Code Catalogue** — 2-column table covering all 44 error IDs from §1.6.

**Hard contract results:**
- Contract 1 (Field-Name Coverage): PASS — 82/82 entity fields, 57/57 endpoint inputs, query params present, 0 missing.
- Contract 2 (Rule Coverage): PASS — 9 validation priorities expressed in §2.9 in order; 2 OCC rules expressed (write endpoint + expected-version field + `ERR_STALE_VERSION`/412, no race framing); all 30+ state transitions expressed with from/to states, preconditions, and side effects; all 9 calculations expressed as reconstructible prose (714-month age threshold, floor-then-sum vesting, largest-remainder allocation with `AFTER_TAX`→`EMPLOYER_PRETAX`→`PRE_TAX`→`ROTH` tie-break, pinned gross→basis→taxable→withholding→net order, 20% half-up withholding, inclusive 60-day window, qualified-offset Oct-15 variant, corrected 1099-R taxable formula, deterministic document list order, equality-completes redeposit rule); all 44 error IDs mentioned in prose; freeze cascade's three links, disbursement compensation invariant, and 5498/1099-R auto-correction chains all stated.
- Contract 3 (§3 Path Purity): PASS — 570 backtick tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos.

**Constraint compliance:** Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced at any point.

## Step 5: Generate Unit Tests — 2026-08-11T05:13:00.000Z

Generation complete. All verification gates pass on disk.

## Summary

**Queue A (difficulty, §1.8): 22 of 23 instances translated, 44 tests (exactly 2 per instance). 1 skipped.**
- SKIP `resource_temporal_overlap/freeze_window_closed_interval_collision`: PRD §2.10 is self-contradictory on the instance's central claim — it pins "closed interval … both the start date and the end date are inside the blackout" with "closed-interval collision semantics" (shared endpoint 2026-06-20 ⇒ overlap), yet also states "windows that merely touch at a boundary date (one ends on the day another begins) do *not* overlap and are allowed" (shared endpoint ⇒ allowed). The asserted `ERR_FREEZE_WINDOW_OVERLAP` on the shared-endpoint pair is not uniquely derivable.

**Queue B (corner, §1.9): 42 of 45 non-stub instances translated, 42 tests (1 each). 3 skipped. All 23 `excluded_because:` stubs left untranslated; every stub's difficulty-instance cross-reference resolves.**
- SKIP `validations/amount_exceeds_vested_rejected`: instance asserts `ERR_AMOUNT_EXCEEDS_VESTED` at case creation; PRD §3.3 pins the amount check to the submit walk-through ("and only then the amount check") — create-time rejection is not uniquely derivable.
- SKIP `validations/same_plan_transfer_rejected`: instance triggers at `POST /v1/rollover-cases`; PRD §3.3 names `ERR_SAME_PLAN_TRANSFER` inside the submit-time cross-reference gate only — not uniquely derivable at creation.
- SKIP `consistency_model/immediate_read_after_write_consistency`: instance asserts vested 9,800,000 after the 1,000,000 partial assembly, but PRD §3.2's floor-per-row-then-sum recomputation over post-debit rows uniquely yields 9,844,444 (EMPLOYER_PRETAX 1,888,889 @ 60% floors to 1,133,333). PRD does not derive the asserted value.

**Notable adjudication:** three doc-loop instances (`case_review_docs_cycle`, `approve_with_documents_outstanding_rejected`, `document_rejection_reopens_docs_loop`) were translated with reader-agnostic flows — PRD §3.4 attaches bubble-up to acceptance ("Acceptance … bubbles up"), so ELIGIBILITY_REVIEW is reached via an accept with no REQUIRED siblings rather than via bare submits; the asserted cycle/cascade outcomes are preserved.

**Test files (86 tests total, 86 Design tags, one per test, tag = last docstring line):**
- `test_01_plans_and_freeze_windows.py` — 5
- `test_02_participants_and_accounts.py` — 6
- `test_03_case_opening_and_eligibility.py` — 12
- `test_04_documentation_loop.py` — 9
- `test_05_disbursement_assembly.py` — 12
- `test_06_disbursement_and_verification_lifecycle.py` — 8
- `test_07_redeposits_sixty_day_and_notices.py` — 11
- `test_08_tax_forms.py` — 7
- `test_09_transfers_loans_conversions.py` — 11
- `test_10_security_and_concurrency.py` — 5

**Infrastructure:** `test_helpers/` contains `__init__.py` (barrel), `types.py` (13 entity TypedDicts + 17 enums), `api_client.py` (46 endpoint methods), `api_errors.py` (46 error ids → HTTP map, registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (entity-backed `make_participant_headers` builder + opaque role builders; proc-1/proc-2 SoD pair), `fixtures.py` (composite builders through approved/issued/acceptance-pending lifecycle states), plus `test_suite/conftest.py`.

**Verification results:** `py_compile` clean on all 21 files; every test module imports against the real framework; 156/156 quoted docstring spans survive whitespace-normalized literal match against PRD.md; zero `skip`/`skipif`/`xfail` markers; zero scaffold references in generated code; no bogus or stub-pointing Design tags.

## Step 6: Generate Implementation — 2026-08-11T05:13:00.000Z

Implementation complete. Summary:

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_1154_rollover_plan_plan_transfer_processing/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher: guarded `pip install` (no-op once Flask present), `exec python3 app.py`, reads `$PORT` (default 10000), binds `0.0.0.0` |
| `requirements.txt` | 1 | flask>=3.0,<4.0 |
| `app.py` | 75 | App assembly, ApiError/404/405/500 handlers, blueprint registration |
| `db.py` | 86 | In-memory store (dicts keyed by id), logical clock (default exactly `2026-05-01T00:00:00Z`), `create_entity`/`touch` (version+1, updated_at on every mutation) |
| `errors.py` | 191 | ApiError + one factory per catalog entry (exact error_ids and HTTP statuses) |
| `response.py` | 40 | Envelope: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`, pagination in `meta` |
| `middleware.py` | 121 | `X-User-ID`/`X-User-Role` auth (401), per-endpoint RBAC (403), payload validators, limit/offset pagination (default 10, 1–100) |
| `services.py` | 504 | Calculations (age months, floor-per-row vesting, largest-remainder allocation with pinned `AFTER_TAX<EMPLOYER_PRETAX<PRE_TAX<ROTH` tie-break, round-half-up basis/20% withholding, 60-day window, eligibility branch priority), 1099-R/5498 drafting + supersession chain, freeze/cancel compensation, serializers |
| `routes_plans.py` | 186 | Plans CRUD + freeze (3-link cascade: SUSPEND → CANCEL PENDING disbursements → exact balance restore) / unfreeze (resume prior_status) / terminate / freeze-windows (closed-interval, adjacency allowed) |
| `routes_participants.py` | 49 | Register (separation_date required for SEPARATED/RETIRED), get with computed ages, ownership masking |
| `routes_accounts.py` | 133 | Account open (uniqueness 409, per-source invariants), list/get with computed totals, source-balances, redeposits |
| `routes_loans.py` | 182 | Loan create/list/get/redeposits, transfer (all PRD-ordered gates), offset (qualified → Oct 15 of next year, else +60d; 1099-R drafted) |
| `routes_cases.py` | 498 | Case create (per-type structural rules, ownership masking, frozen-plan block, open-case exclusivity, vested check last), list/get, PATCH (OCC `expected_rollover_case_version` → 412, replace election set), submit (PRD-priority validation, eligibility snapshot, pinned doc-set ordering, auto-routing), cancel, decide-eligibility (APPROVE/DENY/REQUEST_DOCS with type-based routing to ELIGIBLE vs ACCEPTANCE_PENDING), 5 sub-resource lists, verification create |
| `routes_execution.py` | 303 | issue-disbursement (SoD, verification gate, allocation + withholding + forfeiture, ledger debit), confirm-receipt, execute-transfer (loans gate, book-entry move preserving basis/vesting, source CLOSED, no 1099-R), execute-conversion (PRE_TAX/AFTER_TAX only, ROTH basis credit, irrevocable), post-credit (INBOUND verification, after-tax capability, basis-tracked credit, 5498) |
| `routes_docs.py` | 96 | Document submit/resubmit + review with bubble-up (advances only when no REQUIRED and no REJECTED rows) and rejection reopen; verification complete |
| `routes_disbursements.py` | 164 | issue (freeze-window gate, first-issuance anchoring: deadline, 3 notices at +30/+45/+55, provisional/CODE_G 1099-R), cancel (exact pre-issue restoration incl. forfeiture), return, reissue (deadline not restarted) |
| `routes_redeposits.py` | 159 | Create (exactly-one linkage, same-participant, inclusive deadline, remaining-shortfall), credit (PRE_TAX default credit, 5498 update, completion cascade w/ corrected 1099-R), reject |
| `routes_taxforms.py` | 94 | List (7 filters), get, finalize, correct (OCC → 412, SUPERSEDED chain, revision+1, 201) |
| `routes_ops.py` | 85 | Daily sweep (pass 1 notices SENT/SKIPPED, pass 2 INCOMPLETE + cascades; summary counts), `/_clock/set_current_utc` |

## Route count
Scaffold §1.5 actually declares **55** endpoint entries (the brief said 53; `grep -c "- { method:"` returns 55). All **55/55 (method, path) pairs are registered** — verified programmatically against the parsed YAML with zero missing. The only extra routes are Flask's built-in `/static/<path>` and a `/v1/_health` helper.

## Verification results
- `bash -n start.sh`: OK; `start.sh` is executable (`-rwxrwxr-x`)
- `python3 -m py_compile` on all 17 `.py` files: OK
- Fresh-boot smoke: store starts empty (verified `total_count == 0` on lists), no seeding anywhere
- Smoke test: `PORT=18911 bash start.sh` → 200 on a base route; then **115 functional checks across three passes, all passing** — covering auth/RBAC/masking, envelope + pagination meta, freeze cascade with exact compensation, freeze windows, age boundary (713 vs 714 months → CODE_1 vs CODE_7), largest-remainder allocation with basis travel and exact cancel restoration, all five case types end-to-end, SoD 403, OCC 412, document loop, verification gates, redeposit deadline/exceeds gates, loan transfer/offset with qualified Oct-15 deadline, 5498 aggregation, 1099-R provisional→corrected rewrite and auto-correction chain, sweep notice dispatch + INCOMPLETE marking, and plan termination granting PLAN_TERMINATION. Server killed after testing.

One PRD/scaffold conflict resolved in PRD's favor (per the skill's rule): submit-time check order puts cross-reference errors (`ERR_SAME_PLAN_TRANSFER`) before capability/eligibility gates.

## Step 7: Run Tests and Iterate — 2026-08-11T05:32:00.000Z

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each). Initial sweep: 79/86 with the same 7 tests failing in all 8 rounds (deterministic, no flakiness). Post-fix sweep: **86/86 passed in all 8 rounds**.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**

- `test_suite/test_06_disbursement_and_verification_lifecycle.py` — 3 call sites (`test_state_error_beats_freeze_window_on_cancelled_disbursement`, `test_state_error_beats_freeze_window_on_issued_disbursement`, `test_disbursement_issue_inside_freeze_window_rejected`): added `expected_status=201` to `validate_success(api_client.create_freeze_window(...))`. PRD §4 verbatim: "Operations that create a new, stand-alone resource or add a new, distinct resource to a collection return a `201 Created` status code." The implementation's 201 was correct; the default-200 assertion was the bug.

- `test_suite/test_03_case_opening_and_eligibility.py` — 3 tests rewritten to assert the open-case exclusivity rule at case **open** time instead of submit time:
  - `test_open_case_slot_blocks_second_submit_until_predecessor_terminal` → renamed `test_open_case_slot_blocks_second_case_until_predecessor_terminal`; second `POST /v1/rollover-cases` while case1 is non-terminal now asserts `ERR_OPEN_CASE_EXISTS` (409), then cancel predecessor → open succeeds → submit routes to `DOCS_PENDING`.
  - `test_open_case_slot_occupation_starts_at_creation` — case1 left in DRAFT now blocks the second **open** (409), proving occupation begins at creation; after cancel, open + submit succeed.
  - `test_case_list_pagination_envelope` — setup now cancels case1 before opening case2 (PRD §3.3: "at most one non-terminal case at a time"); the CANCELLED row persists, so `total_count == 2` and created_at-ASC ordering assertions are unchanged.

  Rationale: PRD §3.3 states verbatim "a case occupies its source account **from creation**" and "a second case **opened** on the same account while the first is still in flight **is rejected** with `ERR_OPEN_CASE_EXISTS`", with "The open-case exclusivity rule ... guards **here too**" at submit — the always-on invariant and the "too" pin the rejection to the open; the scaffold's "DRAFT allowed" recipe contradicted the PRD rendering.

**Fixes applied to `implementation/`:**

- `workspace/implementation/routes_cases.py` (`create_case`) — removed the creation-time `ERR_PLAN_FROZEN` gate (formerly lines 118–123). PRD §3.3 scopes that state guard to the submit flow verbatim ("The **submit** then enforces its checks ... the source plan must be `ACTIVE` (a `FROZEN` plan yields `ERR_PLAN_FROZEN`...)"), and the creation paragraph names no plan-state gate; the gate at creation was behavior beyond PRD. The submit-time frozen check and both open-case exclusivity checks (creation + submit backstop) are retained as PRD-required.

Orchestrator verification: all 8 `workspace/implementation/results.{1..8}.json` files exist on disk, each reporting total=86, passed=86, failed=0, errors=0, skipped=0.

## Step 8: Finalize PRD — 2026-08-11T05:42:00.000Z

`PRD_FINALIZED.md` exists on disk at `workspace/PRD_FINALIZED.md` with exactly one edit.

## Summary

**Line counts:** PRD.md = 372 lines; PRD_FINALIZED.md = 372 lines (edit is intra-line; character delta is one appended sentence, ~0.07% of the file).

**Changes (one bullet per change):**
- §3.3 (case-creation paragraph, line 166) — insert — appended the sentence "Case creation applies no plan-state gate: a DRAFT case may be opened while the source or receiving plan is `FROZEN` (or otherwise not `ACTIVE`); the frozen-plan rejection (`ERR_PLAN_FROZEN`) is scoped to the submit flow described below." — pins the Step 7 implementation fix that removed the creation-time `ERR_PLAN_FROZEN` gate — `workspace/implementation/routes_cases.py:118–120` (comment marking the removal; no plan-status check anywhere in `create_case`, lines 74–144).

**Per-item disposition of the Step 7 diff:**
- test_06 (3 × `expected_status=201` on `create_freeze_window`): no edit — PRD §4 already pins 201-for-creation verbatim, and impl already returns 201 (`routes_plans.py:176`). Pure test bug.
- test_03 (3 rewrites asserting `ERR_OPEN_CASE_EXISTS` at case-open time): no edit — PRD §3.3 already pins "a case occupies its source account **from creation**" plus "guards here **too**" at submit; impl matches at both sites (`routes_cases.py:136–139` creation, `297–305` submit). Test-side misread, not PRD ambiguity.
- implementation `create_case` fix (removed creation-time frozen gate): **edited** — the original over-gating is direct evidence that §3.3's silence + §2.9's generic State-tier listing of `ERR_PLAN_FROZEN` was genuinely ambiguous.

**Pre-edit search log (mandatory for the one edit):**
- (a) Subject: applicability of plan-state gates (`ERR_PLAN_FROZEN` / plan `status`) at case creation.
- (b) Impl paths enumerated and read/grepped: `routes_cases.py:74–144` (`create_case` — no plan-status check of any kind; FROZEN/TERMINATED source or receiving plans all permit creation, so the general "no plan-state gate" clause with FROZEN as the named instance is exact); `routes_cases.py:237–238` and `240–241` (submit-time frozen checks for ROLLOVER_IN receiving plan and source plan — covered by "scoped to the submit flow"); `routes_cases.py:197–216` (`amend_case` — no plan-state check, untouched by the wording); `routes_plans.py:83` and `141` (plan-lifecycle `ERR_PLAN_FROZEN` on freeze/terminate — outside the edit's "case creation" scope, not mis-described); `routes_plans.py` freeze cascade (operates on existing cases, not a creation gate). PRD cross-refs checked: §3.1 lifecycle, §3.3 submit paragraph, §3.7 issuance, §4 endpoint table — none state or imply a creation-time gate.
- (c) Wording adjustment made: initially considered naming only FROZEN; widened to the general clause "no plan-state gate" with FROZEN as the instance and "(or otherwise not `ACTIVE`)" parenthetical, because `create_case` has zero plan-status checks — a FROZEN-only sentence would have left TERMINATED-at-creation undetermined and risked a fresh mismatch. Scoped the sentence to "case creation" only, so plan-lifecycle and submit-time gates remain described by existing prose.

## Step 9: Complete PRD — 2026-08-11T05:58:00.000Z

PRD_COMPLETED.md written and verified on disk at `workspace/PRD_COMPLETED.md`.

**Source vs output:** PRD_FINALIZED.md = 372 lines / 62,205 chars → PRD_COMPLETED.md = 377 lines / 69,666 chars (char-delta +7,461; 26 changed-line groups in diff).

**Counts:** ambiguity-pins: 21, mismatch-revisions: 5 (several edits combine both; one bullet per logical change below).

- §2.1 — insert — ambiguity — cross-participant reads of the Participant resource itself are masked as `ERR_PARTICIPANT_NOT_FOUND` — implementation/routes_participants.py:46-48
- §2.2 — insert — ambiguity — `meta.api_request_timestamp` is wall-clock, not the logical clock — implementation/response.py:13, db.py:56-58
- §2.2 — insert — ambiguity — undefined routes/methods return the error envelope with `ERR_VALIDATION` at 404/405 — implementation/app.py:23-30
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION` — implementation/middleware.py:92-114
- §2.3 — insert — ambiguity — list ordering ties broken by insertion order — implementation/middleware.py:117-121, db.py:18
- §2.5 — insert — ambiguity — `created_at`/`updated_at` stamped from the logical clock — implementation/db.py:46-53, 65-82
- §2.8 — insert — ambiguity — expected-version field is a mandatory integer (`ERR_VALIDATION` otherwise); state guard evaluated before version comparison — implementation/routes_cases.py:200-206, routes_taxforms.py:70-76
- §3.1 — insert — ambiguity — negative `spousal_consent_threshold_cents` → `ERR_VALIDATION` — implementation/routes_plans.py:37-41
- §3.1 — insert — ambiguity — terminating a `FROZEN` plan → `ERR_PLAN_FROZEN` (only `ACTIVE` may terminate) — implementation/routes_plans.py:139-141
- §3.3 — revise — mismatch — polymorphic destination (`receiving_plan_id` XOR `receiving_institution_name`) applies to DIRECT/INDIRECT only; `PLAN_TRANSFER` always names the plan — implementation/routes_cases.py:85-100
- §3.3 — insert — ambiguity — `requested_amount_cents` on a `PLAN_TRANSFER` is recorded but ignored at execution (full balance always moves) — implementation/routes_execution.py:170-199
- §3.3 — insert — ambiguity — creation already enforces structural rules, cross-reference consistency, amount positivity, and the vested check (amendment re-checks positivity only) — implementation/routes_cases.py:85-144, 208-211
- §3.3 — insert — ambiguity — submit allowed only from `DRAFT` (`ERR_CASE_INVALID_STATE`); for `ROLLOVER_IN` the plan/account state guards apply to the receiving side — implementation/routes_cases.py:223-245
- §3.3 — insert — ambiguity — exempt types store `qualifying_event` as null — implementation/routes_cases.py:258-262, 313
- §3.3 — revise — ambiguity — "after-tax basis in scope" defined as an `AFTER_TAX` row with `basis_cents` > 0; gate targets the destination plan (source plan for conversions) and does not apply to external institutions — implementation/routes_cases.py:283-295
- §3.4 — revise — mismatch — bubble-up condition is "no row remains `REQUIRED` **or `REJECTED`**" (all rows `SUBMITTED`/`ACCEPTED`), evaluated on both submission and accepting review; a `REJECTED` sibling blocks — implementation/routes_docs.py:25-33, 45-49, 63-67
- §3.4 — revise — ambiguity — document-state check evaluated before case-state check on submit; resubmission clears `reviewed_by` — implementation/routes_docs.py:40-47
- §3.4 — insert — ambiguity — reviewing a non-`SUBMITTED` document → `ERR_DOCUMENT_INVALID_STATE` — implementation/routes_docs.py:59-60
- §3.4 — insert — ambiguity — `request_doc_types` must be a non-empty list of valid types; types already on the case are skipped — implementation/routes_cases.py:397-411
- §3.5 — insert — ambiguity — verifications may be opened in any case status; multiple allowed; any `VERIFIED` row of the required direction satisfies the gate — implementation/routes_cases.py:478-495, services.py:267-271
- §3.7 — insert — ambiguity — the `CODE_G` 1099-R carries `gross_distribution_cents` = case gross and zero withholding — implementation/routes_disbursements.py:85-94
- §3.7 — insert — ambiguity — disbursement cancellation restores balance **and basis**, restores any forfeited remainder, and resets case `forfeiture_cents` to zero — implementation/services.py:405-431
- §3.7 — insert — ambiguity — reissue does not re-evaluate the freeze-window gate — implementation/routes_disbursements.py:152-164
- §3.8 — insert — ambiguity (full silence) — new paragraph pinning execute-conversion: `ELIGIBLE`+type gate, SoD, allocation over `PRE_TAX`/`AFTER_TAX` only, zero withholding, ROTH credited gross to balance and basis, 1099-R with `CODE_7`/`CODE_1` by the 714-month rule, case → `COMPLETED` — implementation/routes_execution.py:210-254
- §3.8 — insert — ambiguity — transfer merge semantics: existing receiving row merges (sums; keeps own `vested_pct`), absent type created fresh, zero/zero rows not copied — implementation/routes_execution.py:170-199
- §3.8 — insert — ambiguity — post-credit: all four breakdown fields mandatory non-negative ints, `roth_basis_cents` ≤ `roth_cents`, positive total; target rows created if absent; `AFTER_TAX` credited to balance and basis; 5498 uses clock-year and accumulates the total — implementation/routes_execution.py:262-300
- §3.8 — insert — ambiguity (silence) — loan creation fields and ranges (`outstanding_balance_cents` > 0, `interest_rate_bp` 0–5000, `term_months` 1–360; born `ACTIVE`, `offset_repaid_cents` = 0) — implementation/routes_loans.py:38-66
- §3.8 — revise — mismatch — loan transfer: nonexistent receiving account → `ERR_ACCOUNT_NOT_FOUND` (existence), not `ERR_ACCOUNT_PARTICIPANT_MISMATCH` — implementation/routes_loans.py:108-115
- §3.9 — insert — ambiguity (silence) — case-linked redeposit requires an anchored `rollover_deadline_date` (else `ERR_CASE_INVALID_STATE`); loan-linked requires `OFFSET` loan with deadline (else `ERR_LOAN_INVALID_STATE`) — implementation/routes_redeposits.py:65-72
- §3.9 — revise — mismatch — case-linked credit always lands in `PRE_TAX` (row created if absent) with basis unchanged; dropped "unless the case's allocation says otherwise" (impl has no such branch) — implementation/routes_redeposits.py:129-133
- §3.9/§3.10 — insert — ambiguity — 5498 credit tax year = calendar year of the redeposit's `received_date`; clock year for `ROLLOVER_IN` post-credit — implementation/routes_redeposits.py:135-136, routes_execution.py:300
- §3.11 — insert — ambiguity (silence) — a due notice whose case is neither `AWAITING_REDEPOSIT` nor terminal (e.g., `SUSPENDED`) stays `SCHEDULED` — implementation/routes_ops.py:40-50
- §4 — insert — ambiguity — `GET /v1/accounts/{id}/loans` is filterable by `status`; unauthenticated `GET /v1/_health` liveness probe documented — implementation/routes_loans.py:69-79, app.py:69-71

Notes on deliberate non-pins: two below-granularity impl artifacts were left unpinned as they are not contract-level behavior — (a) a failed REJECTED review missing `review_note` mutates `reviewed_by` in-memory before the 400 (routes_docs.py:62), and (b) submit of a `ROLLOVER_IN` carrying `requested_amount_cents` hits the generic 500 handler. Everything else observed in implementation/ is now uniquely pinned by the PRD.
