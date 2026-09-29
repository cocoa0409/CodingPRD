# Worklog — task_2258_utility_relocation_betterment_agreement_administration

## Step 1: Create task directory — 2026-09-01T11:30:33.451Z

Created `tasks/task_2258_utility_relocation_betterment_agreement_administration/` and `tasks/task_2258_utility_relocation_betterment_agreement_administration/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T13:24:31.888Z

All three artifacts are complete and the linter is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2258_utility_relocation_betterment_agreement_administration/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2258_utility_relocation_betterment_agreement_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2258_utility_relocation_betterment_agreement_administration/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    74
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1511

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2258_utility_relocation_betterment_agreement_administration/`): `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`. Scenario text stored verbatim (byte-equal after YAML load); `SCAFFOLD.yaml` contains neither design key, and each design file has exactly its one top-level key.

Scaffold size (§1.0–§1.7)
- Entities: 14 (Project, UtilityOwner, UtilityFacility, SubsurfaceInvestigation, UtilityConflict, PriorRightsDetermination, RelocationPlan, PermitRecord, JointTrenchSlot, ScheduleCommitment, ReimbursementAgreement, CostDocument, AuditFinding, DelayClaim)
- State machines: 11 with 63 transitions; ReimbursementAgreement carries two parallel dimensions (`execution_status`, `settlement_status`); shape `cyclic` (plan revision loop, determination appeal loop, audit loop). Plus 2 §1.2.1 concurrency rules (`plan-create-stale-conflict`, `agreement-create-stale-plan`, both ERR_STALE_VERSION/412)
- Calculations: 10, including two dual-variant ones (`prior_rights_state_share` RECORD_BASIS/FIELD_BASIS, `agreement_eligible_cost` ESTIMATE_BASIS/ACTUAL_BASIS), the 9-step `agreement_state_share_settlement` tiered chain, `betterment_credit` (per-line rounding), `delay_claim_allocation`, and the 4-rule ordered `project_clearance_posture`
- Validations: 31, priority-ordered (auth at 2, body/FK at 3–5, segregation of duties at 7, state rules 8–11, fiscal 14/28/29, temporal 22, resource 24–25, settlement 20/21, closure 31)
- Endpoints: 74 (incl. `GET /uro/agreements/{id}/settlement-preview` non-mutating recompute and the `POST /_clock/set_current_utc` test hook)
- Error catalog: 43 ids — all 43 are triggered somewhere across §1.8/§1.9 (verified programmatically)
- RBAC roles: 7 (ProgramAdmin, UtilityCoordinator, RightOfWayAdjudicator, AgreementOfficer, ExternalAuditor, ConstructionEngineer, UtilityOwnerRep — the last is `entity_backed:UtilityOwner`), role model `segregation_of_duties`

Design instance counts
- §1.8 `scaffold_difficulty_design`: 9 rules × 2 = 18 instances
- §1.9 `scaffold_corner_design`: 82 instances across the guide's nine sections in order — entities 14, state_machines 14, calculations 14, validations 10, endpoints 6, errors 13, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1. Of these, 65 carry full `test_recipe` fixtures and 17 are `excluded_because` stubs citing §1.8 instances by name (all references resolve; no stub has a `test_recipe`); all 100 names across §1.8 ∪ §1.9 are unique and every `${var}` is bound by an earlier `captures:`.

Two SCAFFOLD.yaml corrections were needed while writing the last sections: the ProgramAdmin `shared_operations` note wrongly excluded `GET /uro/agreements/{id}/settlement-preview` (that endpoint's §1.5 role list includes ProgramAdmin), and the ERR_OPEN_AUDIT_FINDING fixture had to raise the finding while `settlement_status` is still NOT_STARTED — otherwise the finding's own PENDING_FINAL_INVOICE→AUDIT_IN_PROGRESS cascade makes the priority-10 state rule mask priority 20, leaving that error unreachable.

## Step 3: Copy shared files — 2026-09-01T13:24:31.888Z

Copied `INSTRUCTION.md` → `tasks/task_2258_utility_relocation_betterment_agreement_administration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T13:41:30.449Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **492 lines**, ending at §5 with no audit footer.

**Structure**
- §1 Introduction (3 paragraphs: domain framing, ledger-reconciliation + segregation-of-duties thesis, two cross-cutting design consequences)
- §2 Global Specifications — **11 subsections**: 2.1 Roles/Identity/Segregation of Duties · 2.2 API Response Structure (pasted verbatim from the skill's fragment) · 2.3 Pagination, Ordering and Collection Filters · 2.4 Record Identity, Timestamps and Version Counters · 2.5 The Logical Clock · 2.6 Money, Percentages and Rounding Discipline · 2.7 Stale-Version Guards · 2.8 Derived Figures, Conserved Ledgers and Cascade Propagation · 2.9 Rejection Order: the Validation Ladder (all 31 rungs, in priority order, with exhaustive scopes) · 2.10 Addressing Records and Reverse-Reachability Reads · 2.11 Clearance Posture
- §3 Business Logic — **9 subsections** grouped by workflow (projects/owners; facilities and subsurface truth; conflict identification/sequencing/certification; prior-rights adjudication; plan review and betterment; permitting and joint trench; commitment windows and the delinquency cascade; agreements/cost documents/audit/settlement; delay claims)
- §4 74-row endpoint table, exactly 4 columns (Method | Path | Description | Authorized Role(s)) — all 74 scaffold endpoints present, role lists byte-identical to the scaffold
- §5 43-row error table, exactly 2 columns — all IDs and HTTP statuses match the scaffold, in scaffold order

**Field coverage check:**
- `entities[].fields`: 113 required, 113 present, 0 missing
- `endpoints[].request_body`: 83 required, 83 present, 0 missing
- `endpoints[].query_params`: 17 required, 17 present, 0 missing
- computed read outputs (clearance-summary, settlement-preview, clock): 20 required, 20 present, 0 missing
- Status: **PASS** (135 unique names; two independent derivations — normalized scaffold extraction, plus a broad sweep of every snake_case identifier in the raw scaffold, whose only residue was scaffold metadata keys, calculation names and intermediate formula variables)

**Rule coverage check:**
- `validations[]` with priority: 31 checked, 31 expressed in prose, 0 missing
- `concurrency_rules[]` OCC rejections: 2 checked, 2 expressed (write endpoint + `expected_conflict_version` / `expected_plan_version` + `ERR_STALE_VERSION` all named), 0 missing
- `state_machines[].transitions`: 63 checked, 63 fully expressed (36 as explicit state-pair arrows, 27 as multi-source prose such as "from whichever of `NOT_STARTED`, `PENDING_FINAL_INVOICE`, `HELD` or `AUDIT_IN_PROGRESS` it held"), 0 missing
- `calculations[]`: 10 checked, 10 fully expressed with every constant, ordering rule and rounding point, 0 missing
- `validations[]` conditions: 31 checked, 31 matchable to their `error_id`, 0 missing
- `endpoints[].side_effects` / `applies_to`: 143 side-effect items and 31 applies_to scopes checked, all expressed, 0 missing
- `entities[].fields[]` structured content: 113 checked, 113 reconstructible (enum members, bounds, defaults, immutability), 0 missing
- sibling-branch symmetry: 8 groups checked (permit GRANT/DENY, cost-doc ACCEPT/DISALLOW, relocate/non-relocate certification, on-time/late completion, `RECORD_BASIS`/`FIELD_BASIS`, `ESTIMATE_BASIS`/`ACTUAL_BASIS`, the four delay causes, revise-from-returned/revise-from-appealed), 0 asymmetric
- Status: **PASS**

**Path purity check (§3 only):**
- backtick tokens scanned: 800
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- Status: **PASS**

**Scaffold contradictions resolved in the PRD** (encoded explicitly so the implementer has one answer): `contradicts_record` requires `QL_A` *and* a depth difference strictly above 6 inches (entity field wins over the looser calculation/side-effect wording); `compensable_days` follows the §1.3 formula (late days minus 5 float days, floored, then capped by `claimed_days`); `owner_open_commitment_days` follows the calculation (calendar days across the window with exclusive `window_end`, 15-day example) while `committed_work_days` is still named as the owner's declared input; project listing is `created_at` ascending like every other collection ("newest first" dropped); `expires_on` is stored at application and meaningful only once granted. The two withheld design files were not opened, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T15:35:53.991Z

The suite is complete.

## Files

**`test_helpers/`** (infrastructure, 9 modules): `__init__.py`, `api_client.py` (79 endpoint methods), `api_errors.py` (error-id → HTTP status map), `constants.py` (canonical payloads + verified derived figures), `factories.py`, `fixtures.py` (primitives, readers and a 14-stage `world_*` builder chain), `test_users.py`, `assertions.py`, `types.py`.

**`test_suite/`**: `conftest.py` + 15 test files (`test_01` … `test_15`). Written this session: `test_12_error_catalogue_and_guards.py` (10), `test_13_role_authorisation.py` (5), `test_14_optimistic_concurrency.py` (2), `test_15_project_closure_and_clock.py` (2).

## Counts

- **100 tests**, 100 `Design:` tags — exactly one per test, all pointing at live instances.
- Queue A (Difficulty): **36 tests** covering **18/18** live rule instances (every rule ≥2 tests).
- Queue B (Corner): **64 tests** covering **64/65** live instances (17 `excluded_because:` stubs correctly untouched).
- `pytest --collect-only` collects all 100 cleanly; `pyflakes` clean; every docstring's opening quotation verified verbatim against `workspace/PRD.md`; zero occurrences of "scaffold" in generated code.

## Skipped instance (1)

`Corner/errors/a_second_appeal_on_the_same_determination_is_refused` — reaching rung 27 (`ERR_APPEAL_LIMIT_EXCEEDED`) needs an `ISSUED` determination with `appeal_round == 1`, i.e. a re-issue after appeal. PRD §3.4 requires issuance to find the conflict in `RESOLUTION_SELECTED`, but the first issuance leaves it in `RESPONSIBILITY_SET` and nothing reverts it, so the PRD does not uniquely derive the re-issue path; a second appeal attempted from `APPEALED` would be answered by rung 8 instead. Gap left as a gap.

## PRD-first deviations from the design yaml (asserted the PRD's answer)

- `ERR_AUTHORITY_EXCEEDED` asserted as **409** (PRD §5), not the yaml's 422.
- `finding_type` `UNSUPPORTED_LABOR`/`INADEQUATE_SUPPORT` → `UNSUPPORTED_COST` (only four values exist).
- Predecessor conflict in the dependency test given a non-relocate resolution: the yaml certifies a `RELOCATE` conflict straight from `RESOLUTION_SELECTED`, which §3.3 forbids.
- Stale-conflict OCC test asserts the conflict stays `RESPONSIBILITY_SET` (yaml claimed `RELOCATION_PLANNED`; §3.5 moves it only on approval).
- Project-closure lockdown exercised via conflicts / investigations / trench slots / delay claims rather than the yaml's cost-document leg, because rung 10 (`ERR_SETTLEMENT_STATE_INVALID`) precedes rung 12 on a `SETTLED` agreement.
- "Analyze against an open commitment" test drops the yaml's self-contradictory tail (a cancelled commitment cannot then be reported complete).

## Step 6: Generate implementation — 2026-09-01T15:35:53.991Z

Implementation complete and verified.

**Location:** `workspace/implementation/`

**Files created (19)**

Core modules:
- `app.py` — `create_app()`, blueprint registration, `strict_slashes=False`, error handlers for `ApiError`/404/405/400/500, `app.run(host="0.0.0.0", port=$PORT, threaded=True, use_reloader=False)`
- `db.py` — in-memory `Store` (14 plain dicts keyed by id) + `reset()`, sequence-based ordering, logical clock defaulting to `2026-08-01T00:00:00Z`, graph lookups
- `util.py` — ISO8601 parse/format (3 fractional digits), day math, Decimal/ROUND_HALF_UP helpers
- `errors.py` — 43 error ids with HTTP status map and `ApiError`
- `response.py` — envelope builders (`ok`/`created`/`ok_list`/`error`) with `meta.api_request_id`, timestamp, pagination fields
- `validation.py` — body/query field validators, pagination (`limit` 1..100 default 10, `offset` >=0)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth for the 7 roles, resource lookup, owner-scope checks
- `enums.py`, `calc.py` (all money/share/betterment/settlement/lateness/claim math), `serializers.py` (14 projections), `services.py` (version bumping, project recompute + posture bubble, delinquency hold and release cascades, slot/owner recompute)

Routes package: `routes/__init__.py`, `routes/reads.py` (30 GETs), `routes/admin.py` (8), `routes/conflicts.py` (12), `routes/plans.py` (9), `routes/agreements.py` (15)

Launcher/deps: `start.sh` (executable; `cd` to its own dir, `PORT` default 10000, guarded flask install, `exec python3 app.py` in the foreground), `requirements.txt` (`flask>=3.0`)

**Endpoint count:** 74 — 30 GET, 43 POST, 1 PATCH (44 writes: admin 8, conflicts 12, plans 9, agreements 15, plus `POST /_clock/set_current_utc`).

**Storage:** in-memory dicts only. No SQLite, no JSON files, no disk writes, no seeding — every fresh process starts with all 14 collections empty and the clock at the spec default.

**Boot verification:** `bash start.sh` boots clean from a cold tree (Flask 3.1.3 / Python 3.14.4, ready in ~1s). Post-boot checks: `GET /uro/projects` returns `total_count: 0` (empty store, repeatable), a missing-field POST returns the correct `ERR_INVALID_REQUEST` envelope with a well-formed `req_` id and 3-digit-millisecond timestamp, and an unauthenticated request returns 401. Three independent smoke suites all pass end to end — full happy path, OCC 412 on both versioned writes, separation-of-duties 403s, owner-scope 403, the temporal/fiscal validation rungs, delinquency + hold + release cascades, chronological not-to-exceed cutoff with per-document exclusion, project closure, pagination meta, and the 400/401/404/405 error surfaces. Test servers were killed and `__pycache__` removed; the implementation directory contains only the 19 deliverable files.

## Step 7: Run tests and iterate — 2026-09-01T15:42:20.279Z

The suite is already green and stable. Verified with a full 8-round parallel stability sweep.

## Summary

**Iterations run:** 1 (the first 8-round parallel sweep came back clean, so no further iteration was warranted).

**Sweep result:** all 8 concurrent rounds reported `passed == total == 100`, `failed 0`, `errors 0`, `skipped 0`. Per-round wall time ~137s.

```
results.1.json 100 100    results.5.json 100 100
results.2.json 100 100    results.6.json 100 100
results.3.json 100 100    results.7.json 100 100
results.4.json 100 100    results.8.json 100 100
```

**Integrity checks performed before declaring green** (to rule out a hollow pass):
- Collected count (100) matches the number of `def test_` functions across the 15 suite modules exactly — no missing/uncollected module.
- Zero `skipped` in every round, and no `pytest.mark.skip` / `xfail` anywhere in `test_suite/` or `test_helpers/` (the only grep hit is the word "skipped" inside a docstring in `test_05_settlement_chain.py` describing the not-to-exceed cutoff walk).
- No flakiness signal: the failing-test union across all 8 rounds is empty, so no test passed in some rounds and failed in others.

**Tests deleted:** none — no test failed in any round, so no STEP 1 coverage/unique-derivability adjudication was triggered.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`:** none required.

Key files reviewed for context while the sweep ran: `workspace/PRD.md`, `test_helpers/fixtures.py`, `test_helpers/constants.py`, and `workspace/implementation/calc.py`. Nothing in the task tree was modified; `worklog.md` was left untouched by the subagent.

Orchestrator verification: re-read all 8 `results.*.json` independently — each reports passed=100, total=100, failed=0, skipped=0.

## Step 8: Finalize PRD — 2026-09-01T15:42:20.279Z

**SKIPPED** per the skill's skip condition. Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes — zero iterations beyond the baseline — so `PRD.md` already determined every behavior the implementation exhibits at every site Step 7 touched. No `PRD_FINALIZED.md` produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-09-01T15:57:04.622Z

`PRD_COMPLETED.md` is complete on disk.

## Deliverable
`workspace/PRD_COMPLETED.md`

**Source vs. completed:** `PRD.md` 491 lines / 98,043 chars → `PRD_COMPLETED.md` 492 lines / 107,318 chars (**+1 line, +9,275 chars**). The single added line is one extra bullet inside the existing error-format bullet list in §2.2; every other change is an in-paragraph insert or revision. No new sections, no new paragraphs, no reordering.

**Counts:** 39 changes total — **33 ambiguity-pins**, **6 mismatch-revisions**.

## Per-change log

- §2.1 — revise — mismatch — owner-scope enforcement on reads narrowed from "any read of an owner-scoped resource" to the exact ten reads that enforce it; all collections and the other single reads are unscoped — `routes/reads.py:184,196,219,230,286,321,343,356,367,376`
- §2.2 — insert — ambiguity — unrouted path → `ERR_NOT_FOUND` 404, wrong method → `ERR_METHOD_NOT_ALLOWED` 405, unparseable/non-object body → `ERR_INVALID_REQUEST` 400, absent body read as `{}` — `app.py:40-53`
- §2.3 — insert — ambiguity — `created_at` ties in list ordering fall back to server write order — `db.py:67`
- §2.4 — insert — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` come from the host wall clock, not the logical clock — `db.py:56-58`
- §2.5 — insert — ambiguity — clock endpoint echoes `current_utc` as its sole body key — `routes/admin.py:220`
- §2.5 — insert — ambiguity — clock-stamped fields store the supplied string verbatim rather than re-normalising it — `db.py:32`, `routes/conflicts.py:311`
- §2.6 — insert — ambiguity — `betterment_ratio` serialises as a plain JSON number; client-supplied non-integer inputs are echoed verbatim — `calc.py:103`, `routes/plans.py:73`
- §2.7 — revise — mismatch — drafting an agreement retires nothing; only plan supersession voids the earlier plan's `DRAFT`/`PENDING_OWNER_SIGNATURE` agreements — `routes/agreements.py:53-76`, `routes/plans.py:82-89`
- §2.8 — insert — ambiguity — a row reached by several cascade links in one request is still touched exactly once (`version` +1) — `services.py:16`
- §2.10 — insert — ambiguity — settlement preview is available on any agreement in any state and always reports `ACTUAL_BASIS` figures — `routes/reads.py:325-343`
- §3.1 — insert — ambiguity — a PATCH with no revisable field present is accepted as a no-op — `routes/admin.py:54-59`
- §3.1 — insert — ambiguity — `closure_note` ≤2000 and blank-allowed; closure from any status other than `UNDER_CONSTRUCTION` → `ERR_INVALID_STATE_TRANSITION`, ahead of the posture guard and the three close conditions — `routes/admin.py:75-79`
- §3.1 — insert — ambiguity — `release_note` required 1–2000; releasing a hold on an owner not on hold succeeds — `routes/admin.py:130-134`
- §3.2 — insert — ambiguity — station/offset accept any JSON number and are echoed verbatim; depths are integers — `routes/admin.py:149-156`
- §3.3 — insert — ambiguity — `depends_on_conflict_id` is existence-checked only, any status, any project — `routes/conflicts.py:33-34`
- §3.3 — insert — ambiguity — certifying a `RELOCATE` conflict with no `COMPLETE` commitment → `ERR_INVALID_STATE_TRANSITION` — `routes/conflicts.py:91-95`
- §3.3 — insert — ambiguity — certifying a conflict whose `resolution_type` is still null → `ERR_INVALID_STATE_TRANSITION` — `routes/conflicts.py:101-103`
- §3.4 — insert — ambiguity — opening a determination is ungated on conflict status and several may coexist on one conflict — `routes/conflicts.py:135-161`
- §3.4 — insert — ambiguity — `revision_note` required 1–2000 on return; both revise fields omissible; revise re-derives with the variant forced to `RECORD_BASIS` — `routes/conflicts.py:184,202-220`
- §3.4 — revise — mismatch — issuance accepts a conflict in `RESOLUTION_SELECTED` or, when `appeal_round` ≥ 1, also in `RESPONSIBILITY_SET`; a re-issue leaves the conflict in `RESPONSIBILITY_SET` — `routes/conflicts.py:242-247,261-262`
- §3.4 — insert — ambiguity — the `QL_A`/`contradicts_record` variant flag counts investigations of the facility across all projects — `calc.py:88`
- §3.5 — insert — ambiguity — plan submittal is ungated on conflict status — `routes/plans.py:37-93`
- §3.5 — insert — ambiguity — approval advances the conflict only from `RESPONSIBILITY_SET`; from any other status the plan still becomes `APPROVED` — `routes/plans.py:189-191`
- §3.5 — insert — ambiguity — governing-plan selection breaks a `created_at` tie by the later-written row — `calc.py:236-240`
- §3.6 — insert — ambiguity — a denial retains the recorded `expires_on` and leaves `granted_on` null — `routes/conflicts.py:338-343`
- §3.7 — insert — ambiguity — commitment creation requires plan `APPROVED` and conflict in `RELOCATION_PLANNED`/`RELOCATION_SCHEDULED`, else `ERR_INVALID_STATE_TRANSITION` — `routes/plans.py:219-224`
- §3.7 — insert — ambiguity — a second start-work → `ERR_INVALID_STATE_TRANSITION`; start-work does not bubble `PLANNING` and recomputes without the `CLEAR` bubble, but does refresh the slot row — `routes/plans.py:290-309`
- §3.7 — revise — mismatch — `cancellation_reason` is required (1–500), not optional — `routes/plans.py:359`
- §3.8 — revise — mismatch — no plan-status precondition on drafting; any plan status is drafted against and several agreements may accumulate on one plan — `routes/agreements.py:28-52`
- §3.8 — insert — ambiguity — voiding an already-`VOIDED` agreement → `ERR_INVALID_STATE_TRANSITION`, checked before the `SETTLED` guard — `routes/agreements.py:128-131`
- §3.8 — insert — ambiguity — `support_reference` is required but may be the empty string — `routes/agreements.py:225`
- §3.8 — insert — ambiguity — `exclusion_reason` is optional on `DISALLOW` (stored null if omitted); disposition also increments the agreement's `version`; a non-`SUBMITTED` document is rejected before the parent-agreement check — `routes/agreements.py:256-283`
- §3.8 — insert — ambiguity — `as_built_reference` required 1–120 characters — `routes/agreements.py:165`
- §3.8 — insert — ambiguity — `ESTIMATE_BASIS` figures read the agreement's own `plan_id`, never the conflict's governing plan — `calc.py:166`
- §3.8 — insert — ambiguity — actual-basis document ordering ties break on `created_at` then server write order; `id` is never used — `calc.py:139-140`
- §3.8 — insert — ambiguity — a conflict whose `state_share_pct` is still null is read as 0 in settlement step 7 — `calc.py:197-201`
- §3.9 — insert — ambiguity — `project_id` and `commitment_id` are existence-checked only, in that order; the commitment need not belong to the named project; the claim's `project_id` drives project-scoped rules while the charged owner is the commitment's `owner_id` — `routes/agreements.py:354-362`, `calc.py:314-322`
- §3.9 — insert — ambiguity — analysis is available only from `SUBMITTED`; any other status → `ERR_INVALID_STATE_TRANSITION`, checked before the commitment-state rule — `routes/agreements.py:389-391`
- §3.9 — revise — mismatch — after withdrawal the claim may be **allocated** again on the figures its earlier analysis left in place, but a fresh analysis is not available since the analyse action only accepts `SUBMITTED` — `routes/agreements.py:389-391,441-463`
