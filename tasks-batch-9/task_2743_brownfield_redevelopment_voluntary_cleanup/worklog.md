# Worklog — task_2743_brownfield_redevelopment_voluntary_cleanup

## Step 1: Create task directory — 2026-09-04T00:00:00.000Z

Created pre-assigned task directory `/home/ubuntu/github/CodingPRD/tasks/task_2743_brownfield_redevelopment_voluntary_cleanup` and its `workspace/` subdirectory. Index 2743 was fixed by the scenario number; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T16:57:00.000Z

All three scaffold artifacts are complete and lint-clean in `/home/ubuntu/github/CodingPRD/tasks/task_2743_brownfield_redevelopment_voluntary_cleanup/`.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    70
  §1.1 entities declared:     15
  §1.8 instances scanned:     24
  §1.9 instances scanned:     70
  Calls scanned (§1.8+§1.9):  2281

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files
- `SCAFFOLD.yaml` — 3415 lines, top-level keys `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (neither design key present).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2936 lines, single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4418 lines, single key `scaffold_corner_design`.

All three parse under `yaml.safe_load`; no duplicate YAML anchors; no duplicate instance names across both design files; no forbidden concurrency vocabulary.

## §1.0–§1.7 counts
15 entities · 11 state machines · 2 OCC concurrency rules · 7 calculations · 40 priority-ordered validations · 70 endpoints · 70 errors · 6 roles. Profile: `compliance_audit` + `posture_driven_gating`, layers `[cascading_side_effects, dual_variant_calculation, optimistic_concurrency, ops_run_checkpoint]`, graph topology, parallel state machines, `segregation_of_duties`, `immediate`, `expert_plus`.

## §1.8 — 24 instances
`dual_variant_calc` 2 · `combinatorial_formula` 3 · `non_linear_state_machine` 3 · `transitive_cascade` 2 · `priority_pair_validation_conflict` 3 · `boundary_precision_check` 4 · `cross_entity_state_dependency` 3 · `resource_temporal_overlap` 2 · `compensating_invariant` 2.

## §1.9 — 90 instances (70 test recipes + 20 `excluded_because` stubs)
entities 11 (11/0) · state_machines 15 (10/5) · calculations 15 (9/6) · validations 19 (12/7) · endpoints 7 (7/0) · errors 11 (11/0) · rbac 6 (6/0) · cross-cutting complexity layers 5 (3/2) · consistency model 1 (1/0). Every `excluded_because` citation resolves to a real §1.8 instance name.

## Design adjudications made in this final pass
- **Error triggerability is exhaustive**: all 70 catalog codes are now named in the design files. The `errors` section was written specifically to close the 29 remaining gaps (11 `*_NOT_FOUND` in one instance, the four priority-12 aggregate state codes, `ERR_INQUIRY_DEFICIENT`/`ERR_PHASE_I_NOT_APPROVED` as a priority pair, `ERR_DELINEATION_REQUIRED`/`ERR_NO_CLEANUP_GOALS`, `ERR_BASIS_PHASE_INELIGIBLE`, `ERR_MEDIA_NOT_DELINEATED`, `ERR_PLAN_REVISION_LIMIT`, `ERR_GOALS_NOT_ATTAINED`, `ERR_CERTIFICATION_OUTSIDE_COVERAGE`/`ERR_RESULTS_BEFORE_WINDOW`, `ERR_UNRESTRICTED_SCOPE_NOT_SUPPORTED`, `ERR_ATTACHMENT_POINT_TOO_LOW`); the two OCC codes were moved to the `optimistic_concurrency` layer where the guide puts them.
- **`ERR_ATTACHMENT_POINT_TOO_LOW` needed a purpose-built cost basis.** With the shared cost_lines the attachment point always clears the 1.05 test, so a cheap single-line plan (direct 50,000,000 → quote attachment 87,587,500, limit 30,000,000 ≥ the 25,000,000 minimum, premium pinned at the 2,500,000 `MIN_PREMIUM_CENTS` floor) is edited post-quote to direct 100,000,000 (total_estimate 127,860,000, `round_half_up(×1.05) = 134,253,000`), which isolates priority 50 from priority 51.
- **RBAC probes exploit the priority ladder rather than deep fixtures**: priority 2 precedes the priority 4/5 existence checks, so forbidden-role calls use fabricated path ids. Two such probes had to drop `expected_remedial_action_plan_version` entirely — the linter rejects literal OCC versions and no legitimate captured version exists in that fixture — which is also semantically right (403 precedes both 422 and 412).
- **The guide's `ERR_UNAUTHORIZED` maps to this scaffold's `ERR_FORBIDDEN_ROLE` (403)**; recorded explicitly in the rbac section header.
- **`ops_run_checkpoint` has no row in the claim-extraction guide's layer table** but is a declared layer, so it got a real instance: the compliance sweep is the only channel that can move `AAI_COMPLETE → AAI_STALE`, and only for an `UNDER_CONTRACT` site — which required a second site that is never acquired.
- **OCC staleness is demonstrated by a cascade the client never issued** (the first PASS certification bumps `RemedialActionPlan.version` via the enrollment cascade), which is stronger than a self-inflicted stale read.
- Skipped without ceremony: the guide's `soft_delete`, `idempotency`, `bulk_operations`, `multi_tenancy`, `eventual`/`saga` rows (not in this scaffold's profile), and a second segregation-of-duties instance — the void-certification variant is already a real §1.9 validations test, so only the plan-approver-cannot-issue-the-letter rule was added.

## Step 3: Copy shared files — 2026-09-04T16:58:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T17:16:00.000Z

PRD generation complete.

**Output:** `workspace/PRD.md` — **508 lines**, 16,450 words, 120,572 bytes. Written incrementally (1 `Write` + 9 appends), never one-shot.

**Sections written (29 headings):**
- §1 Introduction
- §2 Global Specifications, 10 subsections: 2.1 RBAC / 2.2 Response Structure (verbatim) / 2.3 Pagination / 2.4 Identity, Audit Fields & Logical Clock / 2.5 Site Cleanup Posture Gate / 2.6 Cascade Depth, Version Propagation & Conserved Quantities / 2.7 Path Resolution & Cross-Aggregate Coherence / 2.8 Monetary & Concentration Precision / 2.9 Version Pinning & OCC / 2.10 Validation Precedence (19 tiers mapping priorities 1–52)
- §3 Business Logic & Workflows, 9 subsections: 3.1 Registry/parcel/title → 3.2 Phased assessment → 3.3 Risk-based cleanup goals → 3.4 BFPP defence & continuing obligations → 3.5 Enrollment & remedial action plan → 3.6 Cost estimate & cost cap → 3.7 Engineering/institutional controls → 3.8 Monitoring, lab capacity & attainment → 3.9 Funding assembly, closure, revocation & ops-run checkpoint
- §4 API Endpoint Definitions (4-column table)
- §5 Error Codes (2-column table)

**Coverage:** 70/70 endpoints, 15/15 entities (166 fields), 91/91 endpoint input identifiers, 40/40 validations with priority ordering, 70/70 error codes, 11 state machines / 63 transitions, 7 calculations, 2 OCC rules, 6 roles, 96 endpoint side-effect items.

**Hard Contract reports:** Field coverage PASS (166/166 entity fields, 91/91 endpoint inputs). Rule coverage PASS (40/40 validations, 2/2 OCC, 63/63 transitions, 7/7 calculations, 96/96 side-effects, 166/166 field contents, 12/12 sibling-branch symmetry groups). Path purity PASS (1313 backtick tokens scanned in §3, 0 paths, 0 bare methods).

**Precision checks:** §2.2 confirmed byte-identical to `section-2.2-response-structure.md`. §4 table = exactly 4 columns, 70 rows. §5 = exactly 2 columns, 70 rows. Zero fuzzy words remain.

**Tail confirmed complete:** file ends at §5's last table row `| ERR_NO_ELIGIBLE_COST_BASE | 422 |` — a real section boundary, no mid-sentence truncation. Withheld design files were never opened.

**Orchestrator verification (independent of subagent report):** `wc -l` = 508; 29 headings present through §5; `tail -15` ends on a complete table row; §4 has 70 endpoint rows; §5 has 70 error rows; 70 distinct `ERR_*` tokens. Not truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T18:15:00.000Z

Implementation complete.

## Files written

All under `workspace/implementation/`:

| file | lines |
|---|---|
| `start.sh` (reads `$PORT`, default 8000, binds 0.0.0.0, `exec python3 app.py` in foreground) | — |
| `requirements.txt` | 1 |
| `app.py` | 50 |
| `db.py` (in-memory dicts + logical clock at `2026-08-01T00:00:00Z`) | 165 |
| `errors.py` | 94 |
| `response.py` | 98 |
| `middleware.py` | 63 |
| `validation.py` | 193 |
| `routes/__init__.py` (`register_blueprints`) | 35 |
| `routes/admin.py` | 192 |
| `routes/common.py` | 67 |
| `routes/sites.py` | 214 |
| `routes/phases.py` | 267 |
| `routes/protections.py` | 236 |
| `routes/enrollments.py` | 163 |
| `routes/plans.py` | 330 |
| `routes/policies.py` | 132 |
| `routes/controls.py` | 187 |
| `routes/funding.py` | 144 |
| `routes/letters.py` | 156 |
| `routes/monitoring.py` | 157 |
| `services/{constants,calc,serialize,derive}.py` | 146 / 185 / 110 / 397 |

Total 3781 lines. Storage is process-local dicts only; nothing seeded, no disk/SQLite/tmp persistence.

## Endpoint coverage

**70/70, verified programmatically** — diffed the Flask `url_map` against `SCAFFOLD.yaml` (method + normalised path): `MISSING []`, `EXTRA []`. Also probed every endpoint with all 6 roles against the live server: **0 role-list mismatches** out of 70.

## Smoke test (PORT=39743, then a fresh boot on 39744)

Full happy path end-to-end, all as expected: party/lab registry → site → PHASE_I + finding + submit + APPROVE → acquisition → liability protection → inquiry-completion → cleanup goal (`goal_ugl` 400.0, cap not applied) → PHASE_II approve (site `delineation_status` DELINEATED) → enrollment (APPLIED→ELIGIBILITY_REVIEW→ENROLLED) → plan with OCC version (`total_estimate_cents` 9778276) → site control → submit → policy quote → technical-review PASS → public-comment-close → approve → control certification PASS → 4 compliant sampling events (`compliant_streak` 4, `attainment_status` ATTAINED) → completion-request → NFA letter issue (`controls_certified_count` 1) → lender-acceptance → funding award AWARD (`allocated_cents` 3850000, assembly `local_match_required_cents` 385000).

Deep-cascade and gate checks also verified live:
- Lab capacity: two overlapping reservations at `concurrent_capacity` 2 succeed, the third intersecting one returns 409 `ERR_LAB_CAPACITY_EXCEEDED`, and a merely *touching* window (starts exactly when another ends) correctly returns 201.
- Exceedance cascade (4 levels in one request): event REPORTED/EXCEEDANCE → control OPERATING→IMPAIRED (`impaired_since` set, `impairment_count` 1) → site `cleanup_posture` RESTRICTED with `impaired_control_count` 1 → letter REVOKED with `revocation_reason` CONTROL_FAILURE → award RESCINDED with `allocated_cents` 0; goal replay dropped the streak to 0/NOT_ATTAINED. Subsequent AWARD and letter re-issue both correctly returned 409 `ERR_SITE_POSTURE_RESTRICTED`.
- Envelope/meta: list `meta` carries `limit/offset/total_count/has_more`; `limit=0` → 422 `ERR_INVALID_REQUEST`; missing headers → 401 `ERR_UNAUTHENTICATED`.
- Fresh boot on a second port: every collection returns `total_count` 0, confirming no seeded state.

Two "failures" in the first smoke run were the script's fault, not the server's: `ERR_LIMIT_BELOW_MINIMUM` on policy bind is correct (the toy plan's estimate puts the computed limit under the 25,000,000-cent floor), and `GET /sites/{id}` as Insurer is legitimately 200 per the scaffold role list.

Both servers were killed by exact PID (`kill 533235`, `kill 548772`) — no pattern-kill was ever used; ports 39743/39744 confirmed free afterwards, and `__pycache__` was removed.

**Orchestrator note:** Steps 5 and 6 were launched as background agents. Step 6 finished first; Step 5 (test generation) was still running at this point, so Step 7 was not started until Step 5 also reported completion. Isolation held — the impl agent was instructed not to read test_suite/test_helpers, and test_suite/ was still empty when it exited.

## Step 5: Generate unit tests — 2026-09-04T21:00:00.000Z

Test generation is complete. All work is at the task root, nothing under `workspace/`.

## Files written

**`test_helpers/`** (9 files, 4,118 lines) — `types.py` 304, `constants.py` 460, `api_errors.py` 184, `api_client.py` 561, `test_users.py` 107, `factories.py` 627, `assertions.py` 378, `fixtures.py` 1,160, `__init__.py` 337.

**`test_suite/`** (19 files, 8,739 lines) — `conftest.py` 34; queue A: `test_01` 165, `test_02` 271, `test_03` 407, `test_04` 344, `test_05` 363, `test_06` 554, `test_07` 388, `test_08` 434, `test_09` 343; queue B: `test_10` 478, `test_11` 623, `test_12` 864, `test_13` 937, `test_14` 620, `test_15` 911, `test_16` 530, `test_17` 365, `test_18` 108.

## Tests emitted

**204 tests total.** Queue A (Difficulty): 65 tests over 9 rules / 24 instances — every instance >=2 tests. Queue B (Corner): 139 tests over 70 live instances across all 9 sections (entities 11, state_machines 10, calculations 9, validations 12, endpoints 7, errors 11, rbac 6, cross-cutting layers 3, consistency model 1) — every live instance >=1 test.

## Verification (all clean)

- `python3 -m py_compile` on all 28 files: OK. `pytest --collect-only`: **204 collected**, no import or fixture errors.
- Tag audit against both design yamls: 70/70 live corner instances covered, 24/24 difficulty instances covered, 0 tags pointing at a stub or a non-existent name, 0 untagged tests, 0 dual-tagged tests, `Design:` line last in every docstring.
- Citation audit: **204 checked, 0 problems** — every quoted docstring sentence appears verbatim in `workspace/PRD.md`.
- AST import audit: no missing or unused `test_helpers`/framework imports in any test file.
- Scaffold-leak scan (`scaffold`, `Table N`, `§1.x`, design-file names): 0 hits in emitted code.
- `ls -la` confirms `test_helpers/` and `test_suite/` exist at the task root and **no copies exist under `workspace/`**; `__pycache__`/`.pytest_cache` removed. `workspace/implementation/` was never read or written.

## Skips and deviations

- **Only recorded skip:** the `ERR_ASSESSMENT_REVISION_LIMIT` fourth-submit assertion was dropped — PRD §2.10 orders the state-machine check (priority 12) ahead of the revision ceiling (priority 39), so a fourth submit on a `REJECTED` phase cannot uniquely derive the ceiling error. The instance's other assertions are covered.
- **One mechanism substitution (not a skip):** `occ_stale_plan_version_blocks_the_cost_cap_quote` — the design derives the stale plan version from the PASS-certification cascade, but the PRD never states that cascade increments the *plan's* version (only the enrollment's). The tests instead use the version bump the PRD does pin: "The plan's `version` increments by 1 as well, which is precisely why the next quote needs a refreshed `expected_remedial_action_plan_version`." All of the instance's asserted outcomes (412 `ERR_STALE_PLAN_VERSION`, no policy created, fresh version succeeds at `underwriting_estimate_cents` 139,803,445, prior quote `SUPERSEDED`, funding need unchanged) are preserved and PRD-grounded.
- Carried forward from earlier files: no plan-version bump asserted from the control/enrollment cascade (same PRD gap); no `/revoke` endpoint exists, so revocation is exercised cascade-only.

**Orchestrator verification:** `find workspace -maxdepth 1 -name 'test_*'` returns nothing (no stray test dirs under workspace/); 19 files in `test_suite/`, 9 in `test_helpers/`; independent `pytest --collect-only` run confirms **204 tests collected in 0.47s** with no errors.

## Step 7: Run tests and iterate — 2026-09-04T21:35:00.000Z

Clean 8-round sweep achieved: **204/204 passing in all 8 parallel rounds**, no flakiness.

## Summary

**Iterations run:** 3 (round 1 = suite-wide collection error; round 2 = 193/204 with 11 deterministic failures; round 3 = clean).

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence and was fixable in the test artifact or the implementation.

**Fixes applied to `test_helpers/`**
- `types.py` — dropped the `from typing_extensions import TypedDict` dependency (not installed on this host) in favour of `typing.TypedDict`. This was a total-collection failure: all 8 rounds of iteration 1 reported `total: 0, errors: 1`.
- `factories.py` — `redeveloper_payload` / `consultant_payload` / `insurer_payload` forwarded their per-type defaults as explicit keywords *and* splatted `**overrides`, so any caller overriding `legal_name` (test 05) crashed with `TypeError: got multiple values`. Routed all three through a new `_typed_party_payload` that merges defaults with overrides before calling `party_payload`.

**Fixes applied to `test_suite/`**
- `test_01_dual_variant_calc.py::test_the_two_bases_diverge_on_the_same_screening_level` — the test subtracted the two 2-dp `goal_ugl` values in binary float (`250.0 - 166.67 == 83.33000000000001`). Now taken in `Decimal`, matching §2.8's 2-dp quantum.
- `test_03_non_linear_state_machine.py::test_the_third_revision_decision_rejects_instead_of_returning_for_rework` — removed the `review_comment` assertion only (§2.10-style partial-coverage split, BRANCH-ASYMMETRIC SIDE EFFECT): §3.2 says the `REVISION_REQUESTED` landing records "**both** `reviewed_by_user_id` **and** the `review_comment`", but the `REJECTED` landing clause names only `reviewed_by_user_id`. The sibling test `test_the_first_two_rounds_return_the_phase_for_rework` keeps the assertion, since that branch is verbatim covered.
- `test_10_corner_entities.py` — three calls passed a second positional label to the runner's `assert_timestamp_format(timestamp)`, which takes one argument. Labels dropped; assertion unchanged.
- `test_11_corner_state_machines.py::test_one_submit_leaves_the_phase_in_under_review` — expected `version=2`, but §3.2 increments the phase version on the finding *and* on submission (create 1 → finding 2 → submit 3), while the automatic `SUBMITTED → UNDER_REVIEW` step "changes nothing but `status` and `updated_at`". Corrected to 3.
- `test_11_corner_state_machines.py::test_withdrawal_is_barred_once_the_remedy_is_approved` — relaxed to `validate_error_is_one_of([ERR_APPROVED_PLAN_EXISTS, ERR_INVALID_ENROLLMENT_STATE])` plus an explicit 409 status check (ERROR PRECEDENCE SILENCE). Approval cascades the enrollment `ENROLLED → REMEDY_APPROVED`, so the withdraw attempt violates both the state-machine tier (§2.10 priority 12) and the approved-plan bar (priority 41); §3.5 names `ERR_APPROVED_PLAN_EXISTS` without saying it pre-empts the state check, and its `ERR_INVALID_ENROLLMENT_STATE` illustration pointedly lists only `CLOSED`/`REJECTED`/`WITHDRAWN`. Both readings are PRD-faithful.
- `test_13_corner_validations.py::test_a_parcel_may_only_be_registered_against_a_redeveloper_party` — fixture identity bug: it acted as the redeveloper while putting the consultant in `owner_party_id`, so §2.10 priority 6 (ownership) legitimately fired ahead of priority 8 (party typing). Now acts as the consultant's own id under the `Redeveloper` role, isolating the typing rule; the exact `ERR_PARTY_TYPE_MISMATCH` assertion is unchanged.

**Fixes applied to `implementation/`**
- `routes/phases.py::review_phase` + `create_phase`, and `services/serialize.py` (`assessment_phases` field list) — the `review_comment` supplied to `POST /assessment-phases/{id}/review` was validated and then discarded. §3.2 requires the `REQUEST_REVISION` decision to record it ("recording both `reviewed_by_user_id` and the `review_comment`"), so it is now persisted (initialised to null at create) and exposed on the phase resource.

**Notes for the orchestrator:** no `worklog.md` writes; no seeded/preloaded state added (storage remains in-memory dicts); no new endpoints, fields, or capabilities beyond the `review_comment` attribute §3.2 names verbatim. The 11 iteration-2 failures were deterministic across all 8 rounds — no load-induced or timing-sensitive flakiness was observed at any point.

**Orchestrator verification:** independently parsed all 8 `results.*.json` (each ~61 KB, all written at the same timestamp): every round reports `passed=204 total=204 failed=0 errors=0`. Artifacts are present and real — no phantom-sweep. Step 8 will run since Step 7 applied 1 implementation fix.

## Step 8: Finalize PRD — 2026-09-04T21:47:00.000Z

PRD_FINALIZED.md produced at `workspace/PRD_FINALIZED.md`.

## Line counts
- PRD.md: 508 lines; PRD_FINALIZED.md: 508 lines (0.0% delta; 6 lines revised in place, no lines added/removed). Tail is byte-identical — file still ends at the §5 error-code table.

## Changes (one bullet each)
- §3.2 (phase creation defaults) — revise — "A newly opened phase is in `DRAFT` with … `max_exceedance_factor` zero" now also states `submitted_at`, `reviewed_by_user_id` and `review_comment` are all null — `implementation/routes/phases.py:79-81`.
- §3.2 (agency review intro) — insert — one sentence pinning that `review_comment` is a stored phase attribute written only by a `REQUEST_REVISION` decision (null when omitted, on either landing), and that `APPROVE` accepts the field but leaves the stored value unchanged — `implementation/routes/phases.py:211,231-232,264-265`.
- §3.2 (round-3 rejection landing) — revise — the `UNDER_REVIEW → REJECTED` landing now records "`reviewed_by_user_id` and the `review_comment`", removing the branch asymmetry Step 7 hit — `implementation/routes/phases.py:260-266`.
- §3.2 (phase reads) — revise — individual/list phase reads now name `reviewed_by_user_id` and `review_comment` alongside `findings_count` and `max_exceedance_factor` as exposed — `implementation/services/serialize.py:12-18`.
- §3.5 (withdrawal) — insert — pins the error precedence: state-machine precondition ahead of the approved-plan bar, so a withdrawal after remedy approval (enrollment already cascaded to `REMEDY_APPROVED`) reports `ERR_INVALID_ENROLLMENT_STATE` (409), while `ERR_APPROVED_PLAN_EXISTS` (409) is only reachable from an enrollment still in `ENROLLED` — `implementation/routes/enrollments.py:142-148`, `implementation/routes/plans.py:316-319`.
- §3.5 (eligibility paragraph, illustrative list) — revise — "withdrawing an enrollment that is already `CLOSED`, `REJECTED` or `WITHDRAWN`" widened to "whose status is anything other than `ENROLLED`" — `implementation/routes/enrollments.py:143`.

## Per-edit pre-edit search log
1. **Phase creation defaults.** (a) Subject: initial null-valued phase attributes. (b) Enumerated: `routes/phases.py::create_phase` (all inserted keys), `db.insert` (sets `created_at`/`updated_at`/`version=1`), `services/serialize.py` `assessment_phases` field list, `submit_phase` (first writer of `submitted_at`), `review_phase` (first writer of `reviewed_by_user_id`). (c) Named all three nulls actually initialised (`submitted_at`, `reviewed_by_user_id`, `review_comment`) rather than only the Step 7 field, so no field is implied non-null.
2. **Review intro / `review_comment` storage semantics.** (a) Subject: where a supplied `review_comment` is persisted. (b) Enumerated via `grep -rn review_comment`: `routes/phases.py:211` (validation, optional string 1–2000), `:265` (assignment placed *after* the REVISION/REJECT if-else, so it covers both landings), `:231-233` (APPROVE branch — writes `status` + `reviewed_by_user_id` only, never `review_comment`), `services/serialize.py:18`, and `routes/plans.py:206` (plan technical review validates `review_comment` but never stores it; `remedial_action_plans` field list at `serialize.py:41-51` has no such field). (c) Deliberately scoped the sentence to the assessment phase ("a stored attribute of the phase") so it does not imply the plan technical-review branch persists its comment; added "null when the caller omits it" because a comment-less `REQUEST_REVISION` overwrites with null; added "leaves the stored `review_comment` as it was" instead of "leaves it null", since an APPROVE after a prior revision round retains the earlier comment.
3. **Round-3 rejection landing.** (a) Subject: the REJECTED landing's recorded fields. (b) Enumerated: `routes/phases.py:260-266` (shared post-branch writes: `reviewed_by_user_id`, `review_comment`, `db.touch` → version+1), `_mark_inquiry_deficient` at `:197-203` and `:267-268` (PHASE_I side effect fires on both landings — already PRD-covered), `submit_phase:176-178` (the `ERR_ASSESSMENT_REVISION_LIMIT` fourth-submit bar). (c) No adjustment: the added clause is symmetric with the sibling REVISION_REQUESTED sentence and the impl performs both writes identically on both landings.
4. **Phase read exposure.** (a) Subject: fields exposed on phase list/get. (b) Enumerated: `serialize.py::serializer` (single field list drives list, get, create and every transition response; `COMMON` adds `created_at`/`updated_at`/`version`), `routes/phases.py::list_phases`/`get_phase`/`create_phase`/`submit_phase`/`review_phase` (all return `dump_phase`). (c) Phrased as an additive "exposed" list rather than an exhaustive field enumeration, so the other serialized fields are not implicitly excluded.
5. **Withdrawal error precedence.** (a) Subject: which error a post-approval withdrawal returns. (b) Enumerated: `routes/enrollments.py::withdraw_enrollment` (order: role → body → path fetch → `require_owner` → `assert_not_frozen` → status must be `ENROLLED` → approved-plan scan), `routes/plans.py:316-319` (approval cascades `ENROLLED → REMEDY_APPROVED`, guarded on `status == "ENROLLED"`), `routes/plans.py:72,172` (plan filing/submission require `ENROLLED`, so the enrollment cannot re-enter `ENROLLED` later), `errors.py:30,68` (both codes 409), §5 table rows 465 and 503 (both 409). (c) Softened from "unreachable" to "reached only by an enrollment still resting in `ENROLLED` that nonetheless carries an `APPROVED` plan", preserving the `ERR_APPROVED_PLAN_EXISTS` rule that the impl still contains rather than declaring it dead.
6. **Eligibility-paragraph illustrative list.** (a) Subject: the full set of statuses from which withdrawal is refused. (b) Enumerated: `services/constants.py:32` `ENROLLMENT_STATUS` (nine statuses), `routes/enrollments.py:143` (strict `!= "ENROLLED"`), `:110` (completion request requires `IMPLEMENTATION`), `:73` (eligibility requires `ELIGIBILITY_REVIEW`), `routes/letters.py:94` (letter-side enrollment state check). (c) Replaced the three-status list with "anything other than `ENROLLED`" so `APPLIED`, `ELIGIBILITY_REVIEW`, `REMEDY_APPROVED`, `IMPLEMENTATION` and `COMPLETION_REVIEW` are covered too, matching the strict impl check.

## Step 7 items intentionally left unpatched (no PRD silence/mismatch)
`test_helpers/types.py` (typing_extensions import) and `test_helpers/factories.py` (duplicate-kwarg `TypeError`) are pure harness bugs; `test_10`'s extra positional arg to `assert_timestamp_format` is a harness-signature bug; `test_01`'s float-vs-`Decimal` subtraction is already determined by §2.8's 2-dp `goal_ugl` quantum; `test_11`'s `version=3` is already determined by §3.2 (finding +1, submit +1, automatic step touching only `status`/`updated_at`); `test_13`'s ownership-vs-party-typing ordering is already determined by §2.10 priorities 6 and 8, which the impl (`routes/sites.py:49-51`: `require_owner` before `require_party_type`) follows exactly.

**Orchestrator verification:** `wc -l` both = 508; `diff` shows 12 changed lines (6 revised pairs) — PRD_FINALIZED.md is NOT byte-identical to PRD.md, so the pass genuinely ran; tail still ends on the §5 `ERR_NO_ELIGIBLE_COST_BASE` row.

## Step 9: Complete PRD — 2026-09-04T22:23:00.000Z

**Orchestrator decision (recorded per AUTONOMY):** Step 9 was run as **three sequential passes partitioned by implementation module** over one shared `PRD_COMPLETED.md`, rather than a single subagent scan. Rationale: `implementation/` is 3,781 lines across 22 modules and a single scan agent reliably runs out of working context and emits a PRD byte-identical to its source (i.e. the scan never really happened). Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying and edited the file in place.

Partitions: pass 1 = `app/db/errors/response/middleware/validation`, all of `services/`, `routes/{__init__,common,admin,sites,phases}`; pass 2 = `routes/{protections,enrollments,plans,policies}`; pass 3 = `routes/{controls,funding,letters,monitoring}` **plus** the cross-partition §2.5 frozen-gate reconciliation that pass 2 escalated (see below).

### Pass 1 — 15 ambiguity-pins, 6 mismatch-revisions
508 lines / 121,498 chars → 508 lines / 126,358 chars (+4,860).
- §2.1 — insert — ambiguity — unrouted URL answers `ERR_NOT_FOUND` 404 and unsupported method `ERR_METHOD_NOT_ALLOWED` 405, both decided by dispatch before the identity headers; trailing slashes tolerated — app.py:19,28-33
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly twenty random alphanumerics — response.py:11,21
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` and empty/out-of-enum filter values are `ERR_INVALID_REQUEST`; undocumented query params ignored; path identifier resolved *before* pagination/filter inspection — response.py:74-80, validation.py:176-193, sites.py:172-177
- §2.3 — insert — ambiguity — equal `created_at` ties broken by insertion order, never by `id` — db.py:163
- §2.4 — insert — ambiguity — `current_utc` accepted with `Z`/offset/no designator, normalised to UTC; response `data` echoes the supplied string verbatim — db.py:102-118, admin.py:23-30
- §2.10 (priority 3) — insert — ambiguity — absent/empty body treated as `{}`; non-object body is `ERR_INVALID_REQUEST`; explicit `null` == omission; undocumented body fields ignored — validation.py:20-40
- §3.1 — insert — ambiguity — `licence_number` min length 1, no upper bound — admin.py:137
- §3.1 — insert — ambiguity — `acquisition_date` unconstrained against `planned_acquisition_date` and the logical clock — sites.py:90
- §3.2 — insert — ambiguity — `supersedes_phase_id` need only resolve; no same-parcel or status requirement — phases.py:60-61
- §3.2 — insert — ambiguity — missing `aai_report_date` at submit is `ERR_INVALID_REQUEST` — phases.py:185-186
- §3.2 — insert — **mismatch** — on submit the revision ceiling is evaluated **ahead of** the state precondition, so a `REJECTED` phase or any phase with `review_round` >= 3 reports `ERR_ASSESSMENT_REVISION_LIMIT`, not `ERR_INVALID_PHASE_STATE` — phases.py:176-181
- §3.2 — insert — ambiguity — `review_comment` is 1 to 2000 characters — phases.py:211
- §3.2 — insert — **mismatch** — phase approval also re-derives *every* cleanup goal on the parcel (count, `goal_ugl`, cap flag + attainment replay), bumping only the goals whose figures changed — phases.py:248-256
- §3.3 — insert — ambiguity — goal `contaminant_code` is 1–24 chars and, unlike a finding's, not required uppercase — sites.py:122 vs phases.py:113
- §3.3 — insert — **mismatch** — the upsert answers **201** like a first derivation, and rewrites only `screening_level_ugl`/`basis`/`control_credit_type` — sites.py:159-167
- §3.8 — revise — **mismatch** — replay ordering "sole tie-break" corrected to `created_at` then insertion order — derive.py:146
- §3.9 — revise — **mismatch** — waterfall ordering "sole tie-break" corrected to `created_at` then insertion order — derive.py:327
- §3.9 — insert — ambiguity — with multiple `APPROVED` plans on a parcel, the earliest by `created_at` supplies the need — derive.py:61-65
- §3.9 — insert — **mismatch** — impairment revokes closure only on the monitoring-exceedance path; a failing O&M certification restricts the parcel and reverts completion review but leaves letters and awards untouched — derive.py:267-296 (cross-checked monitoring.py:155 `revoke_letters=True` vs controls.py:154 `False`)
- §3.9 — insert — ambiguity — sweep's optional `site_id` must resolve, else `ERR_SITE_NOT_FOUND` — admin.py:42-43
- §3.9 — revise — ambiguity — `swept_obligation_count` counts only duties actually advanced, not duties examined — admin.py:78
- §4 — insert — ambiguity — `/sites/{id}/funding-awards` accepts `status` only; `funding_kind` lives on the global collection — sites.py:213 vs funding.py:72
- §4 — revise — **mismatch** — `GET /assessment-phases` filter list was missing `phase_type` — phases.py:95
- §5 — insert — ambiguity — `ERR_NOT_FOUND`, `ERR_METHOD_NOT_ALLOWED`, `ERR_INTERNAL` documented as routing-level identifiers outside the catalogue — errors.py:74-77, app.py:26-39

Verified already uniquely pinned (no change): all §3.3 goal-derivation constants and step order, all §3.6 estimate/premium constants and rounding order, §3.4 weights/thresholds/compliance formula, §2.4 audit-field and finding-immutability rules, §2.5 posture derivation, the §5 code→status map (errors.py matches row-for-row), and §2.10's ordering of ownership before party typing and the frozen gate before state checks.

### Pass 2 — 17 ambiguity-pins, 5 mismatch-revisions
508 lines / 126,358 chars → 508 lines / 129,580 chars (+3,222). Pass 1's edits verified intact by diff against `PRD_FINALIZED.md`.
- §3.4 — insert — ambiguity — a freshly opened protection also has `aai_phase_id`, `aai_report_date`, `aai_expires_on` null — protections.py:46-60
- §3.4 — insert — ambiguity — a nomination against an already `AAI_COMPLETE` protection also answers `ERR_INQUIRY_DEFICIENT` (only `AAI_PENDING`/`AAI_STALE` are source states) — protections.py:85-87
- §3.4 — insert — ambiguity — obligation `due_date` may be any well-formed date incl. one already past; `recurrence_days` has no upper bound — protections.py:127-128
- §3.4 — insert — ambiguity — a newly imposed duty also has `certified_at` null — protections.py:143
- §3.4 — revise — **mismatch** — imposition forces `OBLIGATIONS_NONE → CURRENT` only for the first duty; later impositions re-read the dimension from the recomputed figures (a lapsed defence-critical duty keeps it `LAPSED`) — protections.py:147 / derive.recompute_protection
- §3.4 — revise — **mismatch** — "the obligation dimension never leaves `LAPSED`" now carves out the void-certification path, which recomputes it to `CURRENT`/`AT_RISK` while `bfpp_status` stays `FORFEITED` and the parcel stays `FROZEN` — protections.py:231-235
- §3.4 — revise — ambiguity — `void_reason` is 1–400 chars; the segregation check precedes the `certification_count >= 1` check; the duty's own `status` is not a precondition (incl. `LAPSED`) — protections.py:210-220
- §3.4 — insert — ambiguity — only one prior period is remembered: a second consecutive void decrements the count and clears `certified_at` but leaves `due_date` unchanged — protections.py:222-227
- §3.4 — insert — ambiguity — a restored `due_date` already in the past lands in `AT_RISK`, never back in `LAPSED` — protections.py:230-231
- §3.5 — insert — ambiguity — `decision_note` is 1–600 chars — enrollments.py:66
- §3.5 — insert — ambiguity — the inquiry guard precedes the restricted-track guard, so failing both reports `ERR_ENROLLMENT_NOT_ELIGIBLE` — enrollments.py:82-92
- §3.5 — insert — ambiguity — `withdrawal_reason` is 1–600 chars — enrollments.py:135
- §3.5 — insert — ambiguity — at filing, `basis_assessment_phase_id` need only resolve to some existing phase; eligibility is tested at submission — plans.py:69 vs 178-186
- §3.5 — insert — ambiguity — a PATCH with the empty subset is accepted and still re-runs the estimate and bumps `version` — plans.py:131-157
- §3.5 — revise — **mismatch** — the restricted-goal coherence test compares the goal's own stored `screening_level_ugl` (not a finding's), the refusal is `ERR_INVALID_PLAN_STATE`, and `review_comment` is 1–2000 chars validated but not persisted — plans.py:206, 217-224
- §3.5 — insert — ambiguity — a technical `REQUEST_REVISION` is not posture-gated (issuable on a `FROZEN` parcel) — plans.py:210-211
- §3.5 — revise — ambiguity — `public_comment_count` is a non-negative integer; `status` must be `UNDER_TECHNICAL_REVIEW` or `PUBLIC_COMMENT` (`ERR_INVALID_PLAN_STATE`) and that test precedes the join test; not posture-gated — plans.py:251-261
- §3.5 — revise — **mismatch** — completion evaluates goals before controls (so failing both reports `ERR_GOALS_NOT_ATTAINED`), and the controls check is skipped when there is no `APPROVED` plan — enrollments.py:113-123
- §3.6 — insert — ambiguity — the plan's `status` is not a precondition of quoting; only binding demands `APPROVED` — policies.py:32-46
- §3.6 — insert — ambiguity — a non-`APPROVED` parent plan at bind is `ERR_INVALID_PLAN_STATE` — policies.py:106-108
- §3.6 — revise — **mismatch** — bind sets `total_funding_need_cents` to `total_estimate_cents` plus the premiums of *every* `BOUND` policy on the plan, not just this one — policies.py:122-128
- §3.6 — insert — ambiguity — the policy's own `QUOTED` test is settled ahead of the parent plan's state check — policies.py:103-108

Pass 2 escalated one cross-partition tension it could not fix inside its partition: §2.5's claim that a `FROZEN` parcel refuses "every mutating endpoint … with exactly three exemptions" is false, since its own partition alone found three more ungated writes. Assigned to pass 3 as the final pass.

### Pass 3 — 11 ambiguity-pins, 9 mismatch-revisions
508 lines / 129,580 chars → 508 lines / 134,324 chars (+4,744).
- §2.5 — revise — **mismatch** — the "every mutating endpoint … with exactly three exemptions" universal replaced with the true closed set of seven, plus an explicit statement that funding `DENY`/`RESCIND` and control retirement *are* gated — services/derive.py:91
- §3.4 (void-certification) — revise — **mismatch** — "one of the three operations permitted even on a `FROZEN` parcel" → "one of the operations §2.5 permits" — services/derive.py:91
- §3.9 (ops-run checkpoint) — revise — **mismatch** — same "three operations" count softened to a §2.5 cross-reference — routes/admin.py:36
- §3.7 — insert — ambiguity — the named plan's `status` is not a precondition of proposing a control — routes/controls.py:42-66
- §3.7 — insert — ambiguity — a `condition` of `FAIL` against an `APPROVED` or `IMPAIRED` control is `ERR_INVALID_CONTROL_STATE`, and both state tests precede the coverage-window test — routes/controls.py:120-132
- §3.8 (filing) — revise — **mismatch** — payload/event-kind pairing is evaluated **last** of the three conditions, notwithstanding §2.10's priority 3; each kind silently discards the other's field; `result_value_ugl` bounded at >= 0 — routes/monitoring.py:114-135
- §3.8 (result derivation) — revise — **mismatch** — `result_status` derivation applies to `SAMPLING` only; a `CONTROL_INSPECTION` keeps `result_status` `PENDING` permanently and `result_value_ugl` null — routes/monitoring.py:140-144
- §3.8 (replay) — insert — ambiguity — the replay runs on every filed event including `CONTROL_INSPECTION`, and the goal is rewritten unconditionally so its `version` bumps even when the figures are unchanged — routes/monitoring.py:147-150
- §3.8 (exceedance) — revise — **mismatch** — the four-level cascade additionally requires the named control's own `status` to be `OPERATING`; when it is not, nothing is revoked or rescinded — routes/monitoring.py:151-156
- §3.8 (exceedance) — insert — ambiguity — a `CONTROL_INSPECTION` verdict of `FAIL` records `control_condition` and nothing else; it never impairs the control — routes/monitoring.py:151
- §3.9 (application) — revise — ambiguity — `eligibility_documents` is 0 to 5 elements and, unlike `eligible_cost_categories`, is not uniqueness-checked — routes/funding.py:41-43
- §3.9 (decision) — insert — ambiguity — a newly awarded application is written twice in one request, so its `version` increments by 2 when the waterfall gives it a non-zero allocation and by 1 otherwise — routes/funding.py:117-121
- §3.9 (decision) — revise — **mismatch** — "A `DENY` has no preconditions at all" corrected: the frozen-site gate applies to all three funding decisions — routes/funding.py:92-93
- §3.9 (drafting) — insert — ambiguity — the parent enrollment's `status` is not a precondition of drafting, and no uniqueness rule limits a parcel/enrollment to one letter — routes/letters.py:29-35
- §3.9 (issuance) — revise — ambiguity+**mismatch** — the `COMPLETION_REVIEW` requirement carries `ERR_INVALID_ENROLLMENT_STATE`, and segregation-of-duties is evaluated *after* the enrollment-state and controls-operating tests rather than at §2.10 priority 7 — routes/letters.py:93-108
- §3.9 (lender reliance) — revise — ambiguity — `lender_reference` is 1 to 64 characters; a defence that is not `ESTABLISHED` (or a missing protection row) is refused with `ERR_LETTER_NOT_CURABLE` (422) — routes/letters.py:137,147-150
- §3.9 (lender reliance) — revise — ambiguity — issuing an `ACCEPTED_BY_LENDER` letter is also `ERR_INVALID_LETTER_STATE` — routes/letters.py:79-81
- §3.9 (re-issuance) — revise — ambiguity+**mismatch** — the `UNRESTRICTED` scope test is re-applied; the enrollment's `status` is deliberately not re-tested; curability precedes controls-operating; `controls_certified_count` is recomputed — routes/letters.py:87-91,109-125
- §4 `GET /site-controls` — revise — **mismatch** — filter list was missing `control_class` — routes/controls.py:95-96
- §4 `GET /monitoring-events` — revise — **mismatch** — filter list was missing `event_type` — routes/monitoring.py:97-98

**§2.5 frozen-gate reconciliation.** `assert_not_frozen` call sites across the whole implementation (22): sites.py:93,135; phases.py:63,124,175,216; protections.py:45,81,133,184; enrollments.py:34,71,107,141; plans.py:70,142,167,211,275; policies.py:40,102; controls.py:44,118,167; funding.py:47,93; letters.py:32,77,142; monitoring.py:47,121. Mutating endpoints that reach a write **without** the gate (7): `POST /_clock/set_current_utc` (no site at all); `POST /compliance-sweeps`; `POST /continuing-obligations/{id}/void-certification`; `POST /remedial-action-plans/{id}/technical-review` with `decision=REQUEST_REVISION` (the gate at plans.py:211 sits inside the `PASS` branch); `POST /remedial-action-plans/{id}/public-comment-close` (no gate anywhere); `POST /vcp-enrollments/{id}/eligibility-decision` with `decision=REJECT` (gate inside the `ENROLL` branch); `POST /site-controls/{id}/operation-certification` with `condition=FAIL` (gate inside the `PASS` branch). `POST /parties`, `POST /laboratories`, `POST /sites` are not site-scoped. Pass 3 chose **accurate enumeration over softening** since the set is small, closed and stable: §2.5 now names all seven with §3 cross-references and states that every other mutating operation on the parcel — funding `DENY`/`RESCIND` and control decommissioning explicitly included — is gated. The two other places asserting a count of "three" (§3.4 void-certification, §3.9 sweep) were changed to reference §2.5 rather than restate the number.

### Step 9 totals and orchestrator verification
43 ambiguity-pins + 20 mismatch-revisions = **63 changes** across the three passes.
- `PRD.md` 508 lines / 120,572 chars → `PRD_FINALIZED.md` 508 / 121,498 → `PRD_COMPLETED.md` 508 / **134,324** (+12,826 chars over PRD_FINALIZED, +11.4%).
- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (diff = 100 changed lines / 50 revised pairs), so all three scans genuinely executed. Heading count unchanged at 27 in both — no sections were added or lost. Tail still ends at the §5 row `| ERR_NO_ELIGIBLE_COST_BASE | 422 |`.
- Confirmed `workspace/implementation/`, `test_suite/` and `test_helpers/` contain **no** `.py` file modified after `results.1.json` was written: Steps 8 and 9 touched PRD prose only, so the recorded 8×204/204 green sweep still describes the shipped code exactly.

## Pipeline complete
All nine steps finished. Final artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 files), `test_suite/` (19 files, 204 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}`, `workspace/implementation/` (22 modules + start.sh + results.1..8.json, all 204/204).
