# Worklog — task_2239_long_term_disaster_recovery_group

## Step 1: Create Task Directory — 2026-09-01T10:28:20.814Z

Created `tasks/task_2239_long_term_disaster_recovery_group/` and `tasks/task_2239_long_term_disaster_recovery_group/workspace/` (pre-allocated name used verbatim; no index scan).

## Step 2: Generate Scaffold — 2026-09-01T12:19:38.725Z (verbatim subagent summary)

All three artifacts are complete and the lint is clean.

Verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2239_long_term_disaster_recovery_group/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2239_long_term_disaster_recovery_group/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2239_long_term_disaster_recovery_group/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     17
  §1.8 instances scanned:     22
  §1.9 instances scanned:     68
  Calls scanned (§1.8+§1.9):  1155

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2239_long_term_disaster_recovery_group/`): `SCAFFOLD.yaml` (3371 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2361), `SCAFFOLD_CORNER_DESIGN.yaml` (4487). `worklog.md` appended with a Step 2 entry.

**SCAFFOLD.yaml (§1.0–§1.7)** — `difficulty_level: expert_plus`; profile `multi_party_negotiation` / `quota_allocation`, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy`, topology `graph`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`, `api_prefix: ""`.
- **17 entities** (Survivor, RecoveryCase, DamageItem, AssistanceRecord, UnmetNeedAssessment, TableSession, CasePresentation, MemberOrganization, FundingCommitment, FundingSource, Disbursement, ConstructionProject, VolunteerGroup, VolunteerDeployment, LodgingSite, HousingAssignment, FollowUpContact).
- **8 state-machine blocks over 7 entities** — RecoveryCase carries two parallel dimensions (`case_status`, system-derived `funding_status`); CasePresentation and RecoveryCase are cyclic (defer→requeue, close→reopen).
- **2 §1.2.1 OCC rules** — `pledge-create-stale-presentation` (412 ERR_STALE_PRESENTATION_VERSION), `disbursement-create-stale-case` (412 ERR_STALE_CASE_VERSION).
- **8 calculations**, 2 dual-variant: `unmet_need_determination` (PURPOSE_MATCHED / POOLED), `volunteer_skill_fit_score` (COVERAGE_WEIGHTED / HEADCOUNT_WEIGHTED); plus `survivor_priority_score`, `verified_damage_total`, `dob_exposure_check`, `restricted_fund_waterfall` (per-line rounded admin retention with a net-cap correction loop), `table_award_assembly` (half-open tier bands → bridge authorization), `case_funding_status_derivation` (5-clause top-down ladder).
- **40 ordered validations**, **65 endpoints**, **62 error codes** (all 62 triggered somewhere in §1.8/§1.9), **8 roles** (IntakeSpecialist, CaseManager, UnmetNeedsChair, MemberOrgDelegate, DisbursementOfficer, ConstructionManager, VolunteerCoordinator, LTRGAdmin).

**§1.8** — 9 rules / **22 instances**: dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 2, transitive_cascade 4, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

**§1.9** — all 9 taxonomy sections / **80 instances** (68 full `test_recipe`s + 12 `excluded_because` stubs): entities 12, state_machines 13, calculations 12, validations 11, endpoints 7, errors 11, rbac 9, cross_cutting_complexity_layers 4, consistency_model 1.

## Fixes found while auditing (mechanical re-checks, not lint-covered)
- 7 dangling `grounds:` refs repaired (bare `validations`, a non-existent `state_machines.FundingSource.*` transition, bracket-form calculation refs, one wrong calculation name). All grounds in both design files now resolve against §1.1–§1.7.
- §1.8 `grounds`/`setup`/`assert` were prose strings; converted to YAML lists per the §1.8 schema (grounds re-authored as structured refs).
- Field-name audit against §1.1 found 7 asserted fields that did not exist. Two were genuinely missing and were added to §1.1 (`LodgingSite.available_beds` computed, `HousingAssignment.released_at` system, with the matching endpoint side-effect lines updated); the rest were assert-side typos fixed to the declared names (`beds_committed`→`beds_requested`, `committed_pledge_cents`→`committed_cents`, `total_need_cents`/`total_offset_cents`, `is_superseded`, `attending_member_org_count`).
- One arithmetic error in a new OCC instance: it asserted `total_net_disbursed_cents 1000000` after an approve with no pay; corrected to `total_committed_cents 1000000` / `total_net_disbursed_cents 0` / `FULLY_COMMITTED`.
- Enum audit over every payload literal: 1 remaining "violation", the intentional `income_band: MIDDLE` negative case.

`selector_policy` stays in `complexity_layers` (sanctioned by §0.2) but emits no §1.9 claim — the claim-extraction guide has no row for it and inventing `claim_type:` names is forbidden.

### Subagent's own in-file note

## Step 2 (subagent-written note) — 2026-09-01

Generated all three scaffold artifacts from the verbatim scenario plus
`skills/prd-bench-scaffold-generator/SKILL.md` only (no sibling task inspected):

- `SCAFFOLD.yaml` (§1.0–§1.7): 17 entities, 8 state-machine blocks over 7 entities
  (RecoveryCase carries two parallel dimensions), 2 §1.2.1 OCC rules, 8 calculations
  (2 dual-variant), 40 ordered validations, 65 endpoints, 62 error codes, 8 roles.
  `difficulty_level: expert_plus`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8): 9 rules / 22 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9): 9 sections / 80 instances
  (68 full `test_recipe`s + 12 `excluded_because` stubs).

`scaffold_lint.py` verdict: clean — 1155 calls scanned across §1.8+§1.9, every call
conforms to §1.5 and every §1.1 FK has reverse-reachability in §1.5.

## Step 3: Copy Shared Files — 2026-09-01T12:19:38.725Z

Copied `./INSTRUCTION.md` → `tasks/task_2239_long_term_disaster_recovery_group/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-01T13:00:00.000Z (verbatim subagent summary)

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2239_long_term_disaster_recovery_group/workspace/PRD.md` — 576 lines, ~14,190 words. The two withheld design files and all sibling task directories were never opened.

## Section list

**§1 Introduction** (3 paragraphs)

**§2 Global Specifications & System-Wide Principles** — 11 domain-derived subsections:
2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim, byte-identical to `section-2.2-response-structure.md`, confirmed programmatically) · 2.3 Pagination · 2.4 Record Identity, Timestamps and the Logical Clock · 2.5 The Two Independent Axes of a Recovery Case · 2.6 Cascade Discipline and Compensating Actions · 2.7 Segregation of Duties · 2.8 Money, Basis Points and Rounding Order · 2.9 Conserved Quantities · 2.10 Stale-Version Guards on Pledges and Payment Requests · 2.11 Path Resolution and Validation Precedence

**§3 Business Logic & Workflows** — 9 subsections:
3.1 Household Intake and the Vulnerability Priority Score · 3.2 Documenting Damage and Verifying It by Inspection · 3.3 Outside Assistance and the Unmet-Need Determination · 3.4 The Unmet Needs Table: Sessions, the Queue and Pledges · 3.5 The Chair's Decision: Award, Defer, Deny · 3.6 Assembling Funds, Clearing Duplication of Benefits, and Paying · 3.7 Construction Phases: Permits, Predecessors and the Suspension Cycle · 3.8 Volunteer Groups, Skill Matching and Hosting · 3.9 Follow-Up, Closure, Withdrawal and Reopening

**§4 Endpoint Definitions** — 65 rows, 4 columns
**§5 Error Code Catalogue** — 62 rows, 2 columns

## Coverage audits

```
Field coverage check:
- entities[].fields: 147 required, 147 present, 0 missing
- endpoints[].request_body/input: 104 required, 104 present, 0 missing
- endpoints[].query_params: 29 required, 29 present, 0 missing
Status: PASS
```
(Two independent enumeration passes run; a third pass confirmed all 131 declared enum members and all 8 structured object/array fields present in backticks.)

```
Rule coverage check:
- validations[] with priority: 40 checked, 40 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 56 checked, 56 fully expressed as explicit FROM → TO pairs, 0 missing
- calculations[]: 8 checked, 8 fully expressed, 0 missing (38/38 numeric constants and 24/24 string constants reconstructible; 2 dual-variant calculations carry both variants plus the authoritative/advisory distinction)
- validations[] conditions: 40 checked, 40 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 121 side-effect blocks + 40 applies_to scopes checked, expressed, 0 missing
- entities[].fields[] structured content: 8 checked, 8 reconstructible from prose, 0 missing
- sibling-branch symmetry: 11 groups checked, 11 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1121
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional scans: 0 fuzzy/approximating words, 0 pseudocode operators (`min(`, `max(`, `==`, `>=`, `sum(`, `round_half_up`) anywhere in §1–§3, and 0 forbidden OCC framings ("simultaneously", "first-writer-wins", "race winner/loser", "arriving together").

Two repairs were made during audit: five transitions (`INTAKE → ASSESSED`, `INTAKE → INACTIVE`, `ASSESSED → INACTIVE`, `DOB_FLAGGED → VOIDED`, `DOB_CLEARED → VOIDED`) were reworded into explicit arrow-pair form, and the deny branch plus the below-ceiling adjourn cascade bullet were thickened to match their sibling branches' prose density.

## Step 5: Generate Unit Tests — 2026-09-01T14:00:00.000Z (verbatim subagent summary)

NOTE (orchestrator): the first Step 5 subagent was terminated early by an upstream API error after completing test_helpers/ and queue A (test_01..test_09). A second subagent was relaunched to resume and complete the artifact; its verbatim summary follows.

Done. The interrupted run is complete and the artifact passes every audit the skill specifies.

## Files written this session

**Queue B test files (new, all under `/home/ubuntu/github/CodingPRD/tasks/task_2239_long_term_disaster_recovery_group/test_suite/`):**
- `test_10_household_and_case_records.py` — 12 tests (`Corner/entities`)
- `test_11_lifecycle_transitions.py` — 10 tests (`Corner/state_machines`)
- `test_12_derived_figures.py` — 7 tests (`Corner/calculations`)
- `test_13_business_gates.py` — 9 tests (`Corner/validations`)
- `test_14_capability_surface.py` — 7 tests (`Corner/endpoints`)
- `test_15_refusal_codes.py` — 11 tests (`Corner/errors`)
- `test_16_role_and_identity_gates.py` — 9 tests (`Corner/rbac`)
- `test_17_versions_and_visibility.py` — 3 tests (2 `Corner/cross_cutting_complexity_layers`, 1 `Corner/consistency_model`)

**Helper additions queue B needed:**
- `test_helpers/test_users.py` — added `make_raw_headers(user_id=None, role=None)` for the absent/unrecognized `X-User-Role` 401 shapes.
- `test_helpers/__init__.py` — exported it.

**Queue A repairs (Stage-2 citation defects found by re-auditing the interrupted run's output, no test logic changed):**
- `test_suite/test_03_non_linear_state_machine.py` — a `DEFER` citation was truncated mid-sentence; extended to the full PRD sentence.
- `test_suite/test_08_resource_temporal_overlap.py` — docstring had added backticks the PRD does not use (`` `status` `` where the PRD writes plain "status").

## Test counts
| queue | source | instances | tests |
|---|---|---|---|
| A | `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (9 rules) | 22 non-stub | 58 |
| B | `SCAFFOLD_CORNER_DESIGN.yaml` (9 sections) | 68 non-stub (12 `excluded_because` stubs left untranslated) | 68 |
| | | **90** | **126** |

## Instances skipped
**None.** All 90 non-stub instances passed the PRD-first two-condition filter (verbatim coverage + unique derivability). Four *sub-assertions* inside otherwise-translated instances were dropped as not uniquely derivable: the literal `created_at` clock value, "no Survivor row is created" (no survivor list endpoint exists to prove absence), and "two distinct `created_at` values" on back-to-back assessment creates; `current_utc`/`released_at` were kept as prefix matches only.

## Final coverage audit
```
queue A instances (non-stub): 22   stubs: 0
queue B instances (non-stub): 68   stubs: 12
tagged tests: 126 across 90 distinct tags
total test functions: 126
TAGS POINTING AT NO INSTANCE:        none
QUEUE A INSTANCES WITH <2 TESTS:     none
QUEUE B INSTANCES WITH 0 TESTS:      none
STUBS TRANSLATED ANYWAY:             none
TESTS WITHOUT EXACTLY ONE Design LINE: none
A covered: 22/22    B covered: 68/68
```
Supporting checks, whole suite: 0 syntax errors, 0 imports missing from `test_helpers`, 0 unused imports, 0 unknown `api.*` methods, 0 occurrences of "scaffold" or `§1.x` references in comments/docstrings, and **0 citation failures** — every quoted fragment in every docstring greps verbatim against `workspace/PRD.md`.

Stale `test_suite/__pycache__` and `test_helpers/__pycache__` deleted. Tests were not executed (Step 7 owns that), and neither `workspace/implementation/` nor any sibling task directory was read.

## Step 6: Generate Implementation — 2026-09-01T14:00:00.000Z (verbatim subagent summary)

Implementation complete and verified.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_2239_long_term_disaster_recovery_group/workspace/implementation/`:

| File | Role |
|---|---|
| `start.sh` (executable) | Launcher: guarded `pip install` (only when Flask is missing) + `exec python3 app.py`; binds `0.0.0.0:${PORT:-10000}` |
| `requirements.txt` | `flask>=3.0.0` |
| `app.py` | `create_app()`, blueprint registration, `strict_slashes=False`, per-request global lock, `ApiError`/`HTTPException`/`Exception` handlers (404→`ERR_NOT_FOUND` family, 400/405→`ERR_INVALID_REQUEST`, else `ERR_INTERNAL`) |
| `constants.py` | Enums, category caps, `ADMIN_RETENTION_BPS=350`, trade codes, role names, bridge tiers |
| `db.py` | In-memory dicts only, `base_record()` / `set_field()` / `mark()` version bumping, `_seq` tie-break sort, logical clock (startup pinned to `2026-08-01T00:00:00Z`) |
| `errors.py` | Error-id → HTTP status map (all 68 catalogue entries) + `ApiError` |
| `response.py` | Envelope builders (`meta.api_request_id` `req_*`, 3-digit-ms UTC timestamps, `response_type`, list `limit/offset/total_count/has_more`) |
| `middleware.py` | Auth (`X-User-ID`/`X-User-Role`), field validators, date/instant parsers, pagination + query filters |
| `lookups.py` | 15 FK resolvers, each raising its entity-specific 404 |
| `services/calculations.py` | Priority score, damage capping, unmet-need determination (both variants), DOB exposure, bridge tiers, skill fit, admin retention (`Decimal`/`ROUND_HALF_UP`) |
| `services/rollups.py` | Survivor / case / org / funding-source / lodging / project / queue recomputes and the suspend/cancel/adjourn cascades |
| `routes/cases.py` | Survivors, cases, damage items, assistance records, assessments, DOB report, closure/withdrawal/reopen, follow-ups (18 endpoints) |
| `routes/table.py` | Member orgs, table sessions, presentations (present/deliberate/decision/requeue), funding commitments + rescind (18) |
| `routes/money.py` | Funding sources, disbursements (create/dob-resolution/approve/pay/reverse/void), `_clock/set_current_utc` (12) |
| `routes/work.py` | Construction projects + transitions + skill-fit, volunteer groups, deployments + transitions, lodging sites, housing assignments + release (17) |

**65 endpoints** registered (verified by enumerating `app.url_map`), matching the PRD §4 capability table one-for-one, with role lists cross-checked against every row.

Storage is in-memory dicts only; nothing is seeded at import or startup (a fresh boot answers `total_count: 0` on every list endpoint).

## Verification

- Fresh-process boot through the real launcher: `PORT=18240 bash start.sh` → `401 ERR_UNAUTHENTICATED` unauthenticated, `201` survivor create with `priority_score: 100`, `version: 1`, `created_at`/`updated_at` = `2026-08-01T00:00:00.000Z`, `404 ERR_CASE_NOT_FOUND`, and a correct list envelope. Server killed afterwards; no ports left listening.
- Happy-path end-to-end script (intake → verification → determination → session → pledge → award with bridge → project → disbursement approve/pay/reverse → closure → reopen → clock → pagination): all assertions pass. Key confirmations: capped roof cost 3,000,000; unmet 3,200,000; award 1,480,000 with `TIER_C` bridge 480,000; allocation line `{net 1000000, retention 35000, gross 1035000}`; funding-source conservation identity `available = total − committed − disbursed − admin_retained` intact after reverse (8,503,200 of 9,000,000).
- Edge-path script (DOB flag → resolution → clear, deferral cycle + requeue, `CAPPED`↔`ACTIVE` derivation via rescission, adjourn cascade, session cancel, lodging half-open adjacency vs. overlap, project SUSPEND 3-hop cascade → RESUME → CANCEL, funding-source expiry on clock advance): all pass, producing exactly the codes the PRD's §2.11 ladder requires (`ERR_CASE_MANAGER_MISMATCH`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_MEMBER_ORG_NOT_ACTIVE`, `ERR_SESSION_HAS_ACTIVE_PRESENTATION`, `ERR_LODGING_CAPACITY_EXCEEDED`, `ERR_PROJECT_NOT_ACCEPTING_VOLUNTEERS`, `ERR_PREDECESSOR_NOT_COMPLETE`, `ERR_PREDECESSOR_CASE_MISMATCH`, `ERR_RESTRICTION_MISMATCH` ahead of `ERR_DISBURSEMENT_EXCEEDS_COMMITMENT`).

Two fidelity fixes made during verification: records created in a request no longer get version-bumped to 2 by same-request roll-ups (`db.py` tracks `g.new_records`), and creating an assessment now always increments `RecoveryCase.version`, not only on the `INTAKE → ASSESSED` edge (`routes/cases.py`).

## Step 7: Run Tests and Iterate — 2026-09-01T14:35:00.000Z (verbatim subagent summary)

All 8 parallel rounds pass at 126/126.

## Summary

**Iterations run:** 2 (sweep 1: 124/126 in all 8 rounds, 2 deterministic failures; sweep 2: 126/126 in all 8 rounds).

**Tests deleted:** none. One assertion removed under STEP 1c partial-coverage handling (below).

**Fixes applied to `test_helpers/`:** none — no fixture/factory/header bug was implicated (both failures were single-test, not shared-setup).

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2239_long_term_disaster_recovery_group/test_suite/test_14_capability_surface.py`, `test_abandoning_an_unapproved_payment_reserves_nothing` — removed `assert voided["void_reason"] == ...` (INPUT/COMPUTED-FIELD SILENCE). PRD §3.6 says only "An officer may abandon a request that was never approved, supplying a `void_reason`" — `void_reason` appears solely as a request input. The same paragraph's creation-field roster enumerates the reason-style attributes that *are* resource fields ("The row is created with `dob_resolution_note` and `reversal_reason` null") and conspicuously omits `void_reason`, so a faithful PRD-only reader can legitimately validate it as input-only without persisting/serializing it. Two-reader test fails → assertion dropped, rest of the test (the verbatim-covered `DOB_CLEARED → VOIDED` transition, untouched funding-source fields, and the second-void `ERR_DISBURSEMENT_INVALID_STATE`) kept intact. Scaffold rule that drove it: `Corner/endpoints/corner_void_is_allowed_only_before_approval_and_touches_no_funding_source`.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2239_long_term_disaster_recovery_group/workspace/implementation/services/rollups.py`, `adjourn_queue_cascade()` — the cascade collected *every* affected case (deferred and denied alike) into `touched_cases` and ran `rewind_presented_to_assessed()` on all of them, so an adjournment that only deferred presentations wrongly rewound the case to `ASSESSED`. PRD §3.5 states verbatim for the deferral branch: "the case's `case_status` stays `PRESENTED`", and §3.5's closing paragraph scopes the rewind to denials ("The case-level rewind `PRESENTED → ASSESSED` — whether it follows a denial at the table or a max-deferral denial at adjournment — fires only when no presentation of that case remains in `QUEUED`, `PRESENTING` or `DELIBERATING`"). Renamed the accumulator to `denied_cases` and populate it only on the max-deferral `QUEUED → DENIED` branch; the deferral branch now `continue`s without touching the case. The max-deferral denial path (rescind `PLEDGED` → `MAX_DEFERRALS_REACHED`, org recompute, `PRESENTED → ASSESSED`) is unchanged and still passes its own tests.

Orchestrator verification: all 8 `results.{1..8}.json` on disk read `126 / 126`.

## Step 8: Finalize PRD — 2026-09-01T14:45:00.000Z (verbatim subagent summary)

Done. `PRD_FINALIZED.md` written with exactly one traced edit.

## Line counts
- `PRD.md`: 575 lines
- `PRD_FINALIZED.md`: 575 lines
- Δ lines: 0 (0.00%); 1 line revised (0.17% of lines touched)

## Changes
- **§3.6 (void paragraph, line 351)** — revise — pinned `void_reason` as a required non-empty *request input only*, explicitly not persisted and absent from the disbursement resource/response — `implementation/routes/money.py:401-413` (`mw.req_str(body, "void_reason")` at :405, never written to the record).

## Per-edit pre-edit search log

**Edit 1 — §3.6 `void_reason`**
- **(a) Subject:** the `void_reason` field — whether it is validated only, or persisted/serialized on the `Disbursement` resource; plus the void endpoint's validation strictness and ordering.
- **(b) Impl paths enumerated (read/grepped):**
  - `grep -rn "void" implementation/*.py implementation/routes/*.py implementation/services/*.py` → exactly three hits, all in `routes/money.py:401-405`. No other writer, reader, cascade or serializer anywhere touches `void_reason`.
  - `routes/money.py:401-413` `void_disbursement()` — `mw.req_str(body, "void_reason")` (validate), then `lookups.disbursement`, then state gate `DOB_FLAGGED`/`DOB_CLEARED` → `ERR_DISBURSEMENT_INVALID_STATE`, then `set_field(status, "VOIDED")` + `db.mark`. Nothing writes the reason.
  - `middleware.py:57-65` `req_str` — required, must be `str`, whitespace-only rejected → `ERR_INVALID_REQUEST`; confirms "required, non-empty string" and that shape validation precedes path resolution (consistent with §2.11 ladder steps 3→4).
  - `routes/money.py:134-155` disbursement creation roster — keys are `case_id, project_id, commitment_id, purpose_code, requested_cents, payee_name, status, dob_pool_cents, dob_exposure_cents, allocation_lines, net_cents, admin_retained_cents, gross_cents, requested_by_user_id, approved_by_user_id, dob_resolution_note, reversal_reason`. No `void_reason` key ever exists on the row.
  - `db.py:153-157` `public()` and `response.py:27-52` — serialization is "whole record minus `_`-prefixed keys", so an unset key simply cannot appear; no synthetic/allowlisted fields.
  - Parallel reason-style fields on the *same* entity that **are** persisted: `dob_resolution_note` (`money.py:224`) and `reversal_reason` (`money.py:370`) — checked so the new sentence would not be read as a general claim about reason inputs.
- **(c) Wording adjustment:** scoped the sentence strictly to `void_reason` ("That `void_reason` …") rather than any general statement about reason/note inputs, so the persisted `dob_resolution_note` / `reversal_reason` paths (and other entities' `rescission_reason`, `suspension_reason`, `cancellation_reason`, `release_reason`, `withdrawn_reason`, `closure_waiver_reason`) remain correctly described by the untouched surrounding prose. Also phrased the response claim as "none appears in the voided row's response" rather than an exhaustive "the response is unchanged apart from X", to avoid a false universal about the envelope.

## Item not requiring a PRD edit
- `services/rollups.py` `adjourn_queue_cascade()` (`denied_cases` accumulator, line 347; deferral branch `continue` at 355; rewind loop at 369-370) was a **pure impl/PRD mismatch fix**: PRD §3.5 already pins verbatim that the deferral branch leaves `case_status` at `PRESENTED`, and that the `PRESENTED → ASSESSED` rewind follows denials only and fires only when no presentation of that case remains in `QUEUED`/`PRESENTING`/`DELIBERATING`. Verified the post-fix impl (including `routes/table.py:133-153`, where both the adjourn and `cancel_instead` paths share the same cascade) matches that prose exactly, so §3.5 was kept verbatim.
- No `test_helpers/` changes existed, and no test deletions occurred, so nothing else was in scope.

## Step 9: Complete PRD — 2026-09-01T15:10:00.000Z (verbatim subagent summary)

`PRD_COMPLETED.md` is complete at `/home/ubuntu/github/CodingPRD/tasks/task_2239_long_term_disaster_recovery_group/workspace/PRD_COMPLETED.md`.

## Counts

- Source `PRD_FINALIZED.md`: 575 lines / 105,136 chars → `PRD_COMPLETED.md`: 577 lines / 118,933 chars (**+2 lines, +13,797 chars**)
- 49 change sites: **42 ambiguity-pins**, **7 mismatch-revisions**
- No new sections; all but one change is an in-paragraph insert/revise (the single added paragraph is a two-line note at the end of the existing §5).

## Changes

- §2.1 — insert — ambiguity — an empty (not just absent) auth header is `ERR_UNAUTHENTICATED` — middleware.py:22-25
- §2.1 — insert — ambiguity — org-identity comparison applies only to `MemberOrgDelegate`; an admin may name any org and `pledged_by_user_id` holds their opaque id — routes/table.py:436,460
- §2.2 — revise — ambiguity — `api_request_id` = `req_` + 20 uppercase alphanumerics — response.py:14
- §2.2 — revise — ambiguity — `api_request_timestamp` minted from the logical clock, not the host — response.py:21, db.py:74-80
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, empty-string params as absent, illegal enum filter → `ERR_INVALID_REQUEST`; query validation precedes path resolution — middleware.py:243-299
- §2.3 — revise — ambiguity — `created_at` ties broken by server creation sequence — db.py:162
- §2.3 — revise — ambiguity — `has_more` = `offset` + page size < `total_count` — response.py:33-42
- §2.4 — revise — ambiguity — `created_at`/`updated_at` read from the logical clock — db.py:74-80
- §2.4 — insert — ambiguity — a record created this request stays at `version` 1 with `updated_at == created_at` — db.py:119-121
- §2.4 — revise — ambiguity — clock capability: `to_iso8601` required non-empty, offsets normalized, bare date as midnight, `EXHAUSTED`/`EXPIRED` untouched, rewind never un-expires, `current_utc` 3 fractional digits, expired ids `created_at` ASC — routes/money.py:419-441, middleware.py:221-238
- §2.6 — revise — **mismatch** — DOB-resolution excluded assistance records are rewritten in place, keeping `updated_at`/`version` (sole exception to per-record versioning) — routes/money.py:220-222
- §2.9 — revise — ambiguity — `EXPIRED` is sticky and outranks the availability derivation; a `total_cents` 0 source is still created `OPEN` — services/rollups.py:144-145
- §2.11 — insert — ambiguity — absent body = `{}`, non-object body rejected, JSON `null` counts as absent, integer fields reject booleans/fractions — middleware.py:37-53,95-97
- §3.2 — insert — ambiguity — verification requires both fields; `verified_cost_cents` non-negative and stored under either outcome — routes/cases.py:221-238
- §3.3 — revise — ambiguity — later determinations still bump the case's `version` — routes/cases.py:343
- §3.4 — insert — ambiguity — member-org status: only ACTIVE/SUSPENDED/WITHDRAWN, `CAPPED` → `ERR_INVALID_REQUEST`, `suspension_reason` optional and never cleared — routes/table.py:62-74
- §3.4 — revise — ambiguity — open-session: declared from `SCHEDULED` only, attendance ids resolved as body FKs first, quorum counted as supplied — routes/table.py:113-128
- §3.4 — revise — ambiguity — queueing a case in a wrong `case_status` → `ERR_CASE_INVALID_STATE` — routes/table.py:180-181
- §3.4 — revise — ambiguity — an already-`PRESENTED` case is still version-bumped, and the session's `version` moves too — routes/table.py:219-222
- §3.4 — revise — ambiguity — present/deliberate take no fields, are state-gated with `ERR_PRESENTATION_INVALID_STATE` first, and deliberate leaves queue/session untouched — routes/table.py:263-298
- §3.4 — revise — ambiguity — `pledged_cents` ≤ 0 is `ERR_INVALID_REQUEST` — routes/table.py:429
- §3.5 — revise — ambiguity — `decided_at` ISO with 3 fractional digits; `decision_note` written only when supplied — routes/table.py:336-338, db.py:49-51
- §3.5 — revise — ambiguity — requeue: `new_session_id` required and may be the current session; non-`DEFERRED` refused first — routes/table.py:385-391
- §3.5 — revise — **mismatch** — adjourn `minutes_note` is validated but not persisted (plus `cancel_instead` default false / `SCHEDULED`-only, no active-presentation check) — routes/table.py:137-150
- §3.5 — revise — ambiguity — max-deferral denial leaves `shortfall_cents` 0 and stamps no decision fields — services/rollups.py:356-357
- §3.5 — revise — ambiguity — rescission: reason required non-empty; PLEDGED leg recomputes the session total and touches no case field; confirmed-leg award recompute only on `AWARDED` — routes/table.py:506-538, services/rollups.py:166-178
- §3.6 — revise — ambiguity — `requested_cents` ≥ 1 and `project_id`/`purpose_code` consistency are shape failures; no `case_status` gate — routes/money.py:114,120-123
- §3.6 — revise — **mismatch** — DOB resolution: declared only from `DOB_FLAGGED`, bad/foreign ids → 400, excluded records' `updated_at`/`version` untouched — routes/money.py:203-222
- §3.6 — revise — ambiguity — `approval_note` not persisted; approval leaves the case's `version` alone — routes/money.py:255
- §3.6 — revise — **mismatch** — `payment_reference` is not persisted; only a `CONFIRMED` commitment moves on pay — routes/money.py:321,344-346
- §3.6 — revise — ambiguity — reversal: `EXHAUSTED → OPEN` unless `EXPIRED`, closure rewind conditional, only a `DISBURSED` commitment moves — routes/money.py:384-395
- §3.6 — revise — ambiguity — dob-report: `sibling_case_ids` `created_at` ASC, counts all APPROVED/PAID siblings, writes nothing — routes/cases.py:367-385
- §3.7 — insert — ambiguity — `required_trade_hours` required but may be empty, trade-code keys, non-negative values; `critical_trades` not validated against those keys — routes/work.py:51-55
- §3.7 — insert — ambiguity — `reason` required only on SUSPEND/CANCEL; `permit_number` meaningful only on PERMIT — routes/work.py:143-147
- §3.7 — revise — ambiguity — PERMIT: `permit_number` optional (stays null), wound-down case → `ERR_CASE_INVALID_STATE` after the predecessor check — routes/work.py:152-164
- §3.7 — revise — **mismatch** — suspension releases housing only for deployments that were `CONFIRMED` — services/rollups.py:308-319
- §3.7 — revise — **mismatch** — CANCEL cascades deployment cancellation (`PROJECT_CANCELLED`) from all three source states, not only `SCOPED`, and never writes `suspension_reason` — routes/work.py:204-208
- §3.8 — insert — ambiguity — `skill_profile` required but may be empty, trade-code keys, non-negative values — routes/work.py:255-257
- §3.8 — revise — **mismatch** — booking gates run project-phase → date sanity → window conflict (PRD had dates → window → project) — routes/work.py:288-307
- §3.8 — revise — ambiguity — skill-fit preview: four required query params judged before lookups, only the ordering half of the date gate, no phase gate, writes nothing — routes/work.py:215-239
- §3.8 — insert — ambiguity — `hours_logged` required only on COMPLETE; `cancellation_reason` optional even on CANCEL and ignored elsewhere; shape before state — routes/work.py:380-386
- §3.8 — revise — ambiguity — CONFIRM housing gate needs one assignment spanning the window, skipped when `requires_housing` is false, refused with `ERR_DEPLOYMENT_INVALID_TRANSITION` after the project gate — routes/work.py:395-401
- §3.8 — revise — ambiguity — `release_reason` required non-empty and checked before status; `released_at` ISO with 3 fractional digits — routes/work.py:565, services/rollups.py:291
- §3.9 — revise — ambiguity — follow-up `notes` required but may be empty; logging touches no case field — routes/cases.py:489-503
- §3.9 — revise — ambiguity — closure review: `review_note` discarded, `ERR_CASE_INVALID_STATE` first, criteria order pinned — routes/cases.py:403-414
- §3.9 — revise — ambiguity — close: state check first, residual-then-CLOSURE_REVIEW order, waiver stored only when supplied, both reasons non-empty when present — routes/cases.py:424-457
- §3.9 — revise — ambiguity — a supplied `withdrawn_reason` selects the withdrawal path before any closure criterion; both legs refuse other statuses with `ERR_CASE_INVALID_STATE` — routes/cases.py:429-441
- §3.9 — revise — ambiguity — `reopen_reason` required non-empty though unstored; non-`CLOSED` → `ERR_CASE_INVALID_STATE` — routes/cases.py:467-471
- §5 — insert — ambiguity — transport-level `ERR_NOT_FOUND` (404) for unknown paths and `ERR_INVALID_REQUEST` (405) for unsupported methods; trailing slash indifferent — app.py:23,47-56

Cross-checks that needed no change: the 62-entry error catalogue and all HTTP statuses match `errors.py` exactly; the §4 role lists match every `mw.authorize` call; the §2.11 ladder matches the actual gate order for presentation creation, pledge creation, disbursement approval and deployment creation; `funding_status` is re-derived on exactly the four events named in §2.5 (routes/table.py:353,533, routes/money.py:353,393).
