# Worklog — task_2626_defensible_space_fuels_inspection_program

## Step 1: Create task directory — 2026-09-03T21:21:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2626_defensible_space_fuels_inspection_program/` and `.../workspace/` per the pre-assigned path. No index scan performed (index fixed by scenario number 2626; concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-03T23:13:00.000Z

All three scaffold artifacts are complete and the lint is clean.

## Files

| File | Lines | Bytes |
|---|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2626_defensible_space_fuels_inspection_program/SCAFFOLD.yaml` | 2834 | 152 KB |
| `/home/ubuntu/github/CodingPRD/tasks/task_2626_defensible_space_fuels_inspection_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1860 | 131 KB |
| `/home/ubuntu/github/CodingPRD/tasks/task_2626_defensible_space_fuels_inspection_program/SCAFFOLD_CORNER_DESIGN.yaml` | 3819 | 254 KB |

`SCAFFOLD.yaml` top-level keys are `scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — no `scaffold_difficulty_design` / `scaffold_corner_design` keys. Each design file has exactly one top-level key.

## SCAFFOLD.yaml inventory

- **domain**: `defensible-space-fuels-inspection`, `api_prefix: /fire-district`; archetypes compliance_audit + temporal_windowing; layers cascading_side_effects, dual_variant_calculation, optimistic_concurrency, ops_run_checkpoint; role_model segregation_of_duties; consistency immediate.
- **14 entities**: InspectionCycle, Community, Parcel, Inspector, Contractor, Inspection, ZoneEvaluation, HardeningFinding, ViolationNotice, AbatementOrder, CostRecoveryPayment, SupportProgram, SupportEnrollment, ComplianceCertificate.
- **7 state machines** (cyclic: inspection denial↔reschedule, community DEFERRED/LAPSED→ORGANIZING), **2 OCC rules** (`notice-create-stale-parcel`, `enrollment-create-stale-program`), **7 calculations** (parcel_risk_score, zone_deficiency_assessment, notice_compliance_deadline, abatement_cost_recovery, cost_share_award, inspection_priority_rank, program_compliance_metrics), **27 validations** (priorities 10→76), **65 endpoints**, **48 errors**, **7 roles**.

## Design indexes

- `scaffold_difficulty_design`: **18 instances** — 2 for each of the 9 Difficulty Rules (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- `scaffold_corner_design`: **76 instances (60 active + 16 `excluded_because` stubs)** across all nine guide sections — entities 12, state_machines 16, calculations 13, validations 9, endpoints 5, errors 12, rbac 4, cross-cutting complexity layers 4, consistency model 1.
- 94 names total across both files, all unique; every stub cites a §1.8 instance that exists by exact name and carries no `test_recipe`; all 48 error codes are referenced by at least one instance.

## Lint

```
  §1.5 endpoints declared:    65
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  906

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## SCAFFOLD.yaml drifts found and fixed while authoring §1.9 (the audit-pass value)

1. `ERR_ABATEMENT_CAP_EXCEEDED` cited a non-existent per-risk-class `ABATEMENT_AUTH_CAP_CENTS` → now the flat `ABATEMENT_CAP_CENTS (750000)` used by §1.3/§1.4.
2. `ERR_CONTRACTOR_INSURANCE_LAPSED` keyed on `work_end_utc` → now `work_start_utc` ("at or before"), matching §1.2/§1.4 and the field description.
3. `ERR_PROGRAM_WINDOW_CLOSED` described a closed service window while §1.4 priority 44 and the field description say half-open → error condition rewritten as `clock < start or clock >= end`.
4. `ERR_COMMUNITY_THRESHOLD_NOT_MET` named only `certification-decision` although priority 59 also governs `submit-certification` → condition now covers both endpoints with their respective clauses.
5. `verify-completion` side effect listed non-existent fields `labor_cost_cents` / `subsidy_credit_cents` → now the real AbatementOrder cost fields.
6. Priority 42's `applies_to` omitted inspection scheduling, support-program creation, advance and close although `ERR_CYCLE_NOT_ACTIVE`'s condition names them → list and check aligned.
7. `ERR_EXTENSION_LIMIT_REACHED` was unreachable (an already-EXTENDED notice would be answered by priority 40) → priority 68, the extend endpoint description and the ISSUED→EXTENDED transition note now state that EXTENDED is an accepted from-state answered by the count gate.

## Step 3: Copy Shared Files — 2026-09-03T23:13:30.000Z

Copied `./INSTRUCTION.md` → `.../task_2626_defensible_space_fuels_inspection_program/workspace/INSTRUCTION.md` (1424 bytes). Also validated all three scaffold YAMLs parse with `yaml.safe_load` and carry the expected top-level keys.

## Step 4: Generate PRD — 2026-09-03T23:30:00.000Z

PRD generation complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2626_defensible_space_fuels_inspection_program/workspace/PRD.md`
**Size:** 525 lines, 115,655 bytes. Built in ~14 chunked `cat >>` appends (no single giant Write), each verified with `wc -l` / `tail`.

**Section outline**
- `# Defensible Space & Fuels Inspection API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim contract, byte-identical, confirmed by exact substring match against `section-2.2-response-structure.md`); 2.3 Pagination; 2.4 Record Identity, Timestamps and Revision Counters; 2.5 The Logical Clock; 2.6 Resource Resolution and Reference Integrity; 2.7 Precision, Rounding and Money; 2.8 Stale-Read Protection on Parcel and Program Writes; 2.9 The Request-Screening Ladder (all 27 numbered gates in ascending priority order); 2.10 Conserved Quantities and Cascade Discipline — **10 subsections (within 8–12)**
- `## 3. Business Logic & Workflows` — 3.1 The Fire-Season Cycle and its Ops-Run Checkpoint; 3.2 The Parcel Inventory, Risk Classification and the Priority Queue; 3.3 The Inspector Roster and Booking a Visit; 3.4 Serving Notice, Denied Access, and Rebooking; 3.5 Field Evaluation: Zones, Hardening, and Closing Out the Visit; 3.6 Violation Notices: Service, Deadlines, Extensions and Supersession; 3.7 Abatement Authority: Authorizing, Awarding and Performing the Work (with nested `#### Cost Recovery: Verification, Invoicing, Payment and Liens`); 3.8 Compliance-Support Programs and Cost-Share Awards; 3.9 Documentation, Neighbourhood Certification and Program Metrics — **9 subsections (within 5–9)**
- `## 4. Endpoint Definitions` — intro + 4-column table (Method, Path, Description, Authorized Role(s)), 65 data rows
- `## 5. Error Code Catalogue` — 2-column table (Error ID, HTTP Status Code), 48 rows. File ends here, no audit footer.

**Coverage (covered / declared)**
- Endpoints: **65 / 65** (66 `| `-prefixed rows in §4 = 1 header + 65 endpoints; includes `POST /_clock/set_current_utc`)
- Errors: **48 / 48** in the §5 table, and all 48 also named in §1–§3 prose (verified programmatically, 0 missing)
- State machines: **7 / 7**, all **47 / 47** transitions expressed (34 matched by literal `FROM → TO` arrow phrasing, the other 13 — cycle `ACTIVE → ACTIVE`, the three notice-clear and three notice-void paths, the two order-cancel paths, `REQUESTED → APPROVED`/`WAITLISTED`, and the two enrollment-cancel paths — expressed in descriptive prose and individually spot-verified)
- Calculations: **7 / 7**, including all 6 named variants (`intake_provisional`/`post_inspection_verified`, `district_contracted`/`voluntary_precompliance`, `district_scope`/`community_scope`)
- Validations: **27 / 27** — every priority rung present in the §2.9 ladder in ascending order with its error identifier(s)

**Hard Contract 1 — Field-Name Coverage**
```
Field coverage check:
- entities[].fields: 134 required, 134 present, 0 missing
- endpoints[].request_body: 75 required, 75 present, 0 missing
- endpoints[].query_params: 21 required, 21 present, 0 missing
Status: PASS
```

**Hard Contract 2 — Rule Coverage**
```
Rule coverage check:
- validations[] with priority: 27 checked, 27 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_parcel_version / expected_program_version + ERR_STALE_PARCEL_VERSION / ERR_STALE_PROGRAM_VERSION all named), 0 missing
- state_machines[].transitions: 47 checked, 47 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed (incl. all 6 variants), 0 missing
- validations[] conditions: 27 checked, 27 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 38 checked, 38 expressed, 0 missing
- entities[].fields[] structured content: 14 entities checked, 14 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (pass/fail completion, certify/defer, issue/deny, approved/waitlisted, attended true/false, cancel from AUTHORIZED/AWARDED, cancel from APPROVED/WAITLISTED, district/community metric scope), 8 with equal prose density, 0 asymmetric
Status: PASS
```

**Hard Contract 3 — §3 Path Purity**
```
Path purity check (§3 only):
- backtick tokens scanned: 1014
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Last 3 lines of the file**
```
| `ERR_CONTRACTOR_CAPACITY_EXCEEDED` | 409 |
| `ERR_COST_SHARE_CAP_EXCEEDED` | 422 |
| `ERR_PAYMENT_EXCEEDS_OUTSTANDING` | 422 |
```

The file terminates at a complete section boundary (final row of the §5 error table), not mid-sentence. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

Two notes for the caller: the scaffold's own header comment claims "62 endpoints / 40 error codes" but the actual data is 65 endpoints / 48 errors, so the PRD follows the data. Also, a handful of scaffold rules carry no explicitly declared error code (duplicate hardening `item_code`, extension after deadline lapse, a second live order on one notice, closing a cycle with open field work) — these are documented as falling to the priority-40 general state gate `ERR_INVALID_STATE`, and the notice-void integrity precondition (marshal must differ from `verified_by_inspector_id`) is documented under `ERR_SEGREGATION_OF_DUTIES`.

**Orchestrator verification (truncation guard):** independently confirmed 525 lines / 115,655 bytes; file ends at the completed §5 error table (`ERR_PAYMENT_EXCEEDS_OUTSTANDING | 422`), not mid-sentence. Section headings walk 1→5 with no gaps. Counted exactly 65 endpoint rows (method-prefixed) and 48 unique `ERR_` ids in §5. Grepped for `harder than expert`, `expert level`, `scaffold`, `difficulty_design`, `corner_design`, `test_recipe` — zero hits, so the Step-2-only difficulty instruction did not leak into the PRD. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-04T00:07:00.000Z

Implementation is complete and verified. Server processes started for smoke testing were killed by their exact PIDs (3301179 on port 24372, 3338744 on port 28704); `ss` confirms nothing of mine is still listening, and no broad `pkill` was ever used.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2626_defensible_space_fuels_inspection_program/workspace/implementation/`)

Infrastructure — 3013 lines total across 21 files:

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | executable; guarded pip install, `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `app.py` | 65 | registers 11 blueprints, `strict_slashes=False`, `before_request` version-dedup set, handlers for `ApiError`/404/405/catch-all |
| `errors.py` | 67 | `ApiError`, `ERROR_STATUS` (48 ids → statuses), `fail()` |
| `db.py` | 74 | `Store` with 14 in-memory dicts + logical clock + `_seq`; empty on boot |
| `auth.py` | 49 | 7 roles, `auth(*roles)`, `own()`, entity-backed owner matching |
| `validate.py` | 214 | FK resolution order, typed body getters, window checks, pagination |
| `response.py` | 114 | envelope builder, `jsonable` Decimal/datetime coercion |
| `calc.py` | 311 | all 7 calculations + every PRD constant |
| `domain.py` | 338 | conserved-quantity recounts, posture/score/rank recomputation, cascades, notice issuance |
| `routes/cycles.py` | 185 | 7 endpoints (incl. the 8-step ordered advance) |
| `routes/communities.py` | 120 | 6 |
| `routes/parcels.py` | 219 | 7 |
| `routes/people.py` | 95 | 5 |
| `routes/inspections.py` | 333 | 10 |
| `routes/findings.py` | 60 | 4 |
| `routes/notices.py` | 139 | 5 |
| `routes/abatement.py` | 287 | 9 |
| `routes/support.py` | 234 | 8 |
| `routes/certificates.py` | 75 | 3 |
| `routes/clock.py` | 23 | 1 |
| `routes/__init__.py` | 0 | package marker |

## Coverage

- **Endpoints: 65/65.** I parsed the PRD §4 tables (65 declared, 65 unique) and diffed against `app.url_map`: 65 registered, **0 missing, 0 extra**.
- **Error codes: 48/48.** Every catalogued id is in `ERROR_STATUS`, **no status mismatches**, no wired-but-uncatalogued ids, and **all 48 are actually referenced by handler code** (none dead).
- `python3 -m py_compile` passed on all 20 `.py` files; `__pycache__` removed afterward.

## Storage discipline

Grep for `sqlite3|json.dump|open(|shelve|pickle|/tmp|.db` across the implementation returns **zero hits** — pure dicts. Virgin-process check on a fresh port confirmed `parcels`, `violation-notices`, `cost-recovery-payments`, `zone-evaluations`, `hardening-findings` all return `total_count: 0`, and the clock reads back the `2026-08-01T00:00:00.000Z` epoch. Nothing is seeded.

## Smoke results

Three suites, all green.

**Suite 1 (78 assertions, exit 0, "ALL SMOKE EXPECTATIONS MET"):** 33x200, 20x201, 2x400, 1x401, 5x403, 2x404, 9x409, 1x412, 5x422. Covered every router and validated the arithmetic: envelope shape + `req_`+20 id, risk 95.23 `POST_INSPECTION_VERIFIED`, 11-day CRITICAL/VERY_HIGH deadline `2026-08-26T23:59:59Z`, invoice 63000/20700/15000/12338 -> 111038, tier 0.20 -> subsidy 22208 -> recoverable 88830, due `2027-01-16T23:59:59Z`, payment waterfall 12338/15000/20700/1962 with outstanding 38830 then PAID, contractor committed 6.5 -> 0.0 with completed 7.0, cost-share award 150000 at bonus 0.05 with budget 300000 -> 150000 and a second enrollment WAITLISTED at position 1, ranks [1,2,3]. Distinct error ids exercised include `ERR_INSPECTOR_WINDOW_CONFLICT`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_NOT_RESOURCE_OWNER`, `ERR_PAYMENT_EXCEEDS_OUTSTANDING`, `ERR_MISSING_VENDOR_INVOICE`, `ERR_PARCEL_NOT_INSPECTED`, `ERR_STALE_PARCEL_VERSION`, `ERR_UNAUTHENTICATED`, `ERR_FORBIDDEN_ROLE`.

**Suite 2 (new this round, fully green):** the access-denial/abandonment chain (denial -> `ACCESS_DENIED`, reschedule to a new inspector keeping `access_denial_count` and clearing `notice_method`, second denial -> `ABANDONED` + auto-notice forced to `CRITICAL`/`CERTIFIED_MAIL` at 14 days, third denial -> `ERR_ACCESS_DENIAL_LIMIT_REACHED`), supersession (`SUPERSEDED_BY_NEW_NOTICE`, `open_violation_count` staying at 1), void -> posture back to `PENDING_INSPECTION`, a passing REINSPECTION clearing the notice, certificate `ISSUED` at `2026-10-30T23:59:59Z` then `REVOKED` by a later failing inspection with snapshots preserved, half-open window adjacency accepted while a true overlap 409s, zero-length window -> `ERR_INVALID_TIME_WINDOW`, exemption -> `EXEMPT` with `inspection_priority_rank` nulled, priority-queue paging, cancel-on-`ABANDONED` -> 409.

**Suite 3:** survival-outcome recording (fields set, posture/score/rank untouched), district metrics recomputed on read, and the pagination guards (`limit=0`, `limit=101`, `offset=-1`, non-numeric -> 400 `ERR_INVALID_REQUEST`). I also unit-checked `survival_correlation` directly: 50.00/33.33/16.67 on a mixed pool, `100.00/None/None` and `None/0.00/None` on single-leg pools, and a null (not 0.00) rate when the eligible set is empty — with `PENDING_INSPECTION` and `EXEMPT` correctly excluded from both numerator and denominator per PRD §3.9.

One note for the record: the three "failures" from the pre-existing suite-1 run were wrong expectations in my own smoke script, not implementation defects. The test community's single eligible member had become `COMPLIANT` when the abatement verification cleared its notice, so its rate was legitimately 100.00 and `CERTIFY` correctly returned 200 -> `CERTIFIED`; that in turn made the follow-on `DEFER` and `reopen-organizing` calls correctly 409 `ERR_INVALID_STATE`. I corrected the script's expectations and the suite now passes end to end with no code change.

## Step 5: Generate Unit Tests — 2026-09-04T00:52:00.000Z

Generation is complete. Everything landed at the task root; nothing was written under `workspace/`.

## Files

All paths relative to `/home/ubuntu/github/CodingPRD/tasks/task_2626_defensible_space_fuels_inspection_program/`.

**test_helpers/** (2,560 lines): `__init__.py` 18, `api_client.py` 329, `api_errors.py` 142, `assertions.py` 300, `constants.py` 255, `factories.py` 404, `fixtures.py` 667, `test_users.py` 119, `types.py` 326.

**test_suite/** (7,571 lines): `conftest.py` 17, `test_01_risk_scoring_variants.py` 223, `test_02_cost_recovery_invoicing.py` 233, `test_03_cost_share_awards.py` 127, `test_04_access_denial_loop.py` 150, `test_05_enrollment_completion_forks.py` 223, `test_06_inspection_fail_cascade.py` 229, `test_07_verify_completion_cascade.py` 192, `test_08_validation_priority_pairs.py` 238, `test_09_zone_severity_boundary.py` 158, `test_10_inspector_standing_gate.py` 108, `test_11_certificate_eligibility_gate.py` 174, `test_12_inspector_window_overlap.py` 161, `test_13_contractor_window_overlap.py` 206, `test_14_order_cancel_restores_hours.py` 137, `test_15_enrollment_cancel_restores_budget.py` 184, `test_20_entities.py` 748, `test_21_state_machines.py` 778, `test_22_calculations.py` 714, `test_23_validations.py` 596, `test_24_endpoints.py` 356, `test_25_errors.py` 895, `test_26_rbac.py` 379, `test_27_cross_cutting.py` 229, `test_28_consistency.py` 116.

## Coverage

- **98 tests**, 98 `Design:` tags — exactly one per test, verified by an AST pass that resolved every tag against the two yamls: no untagged, dual-tagged, unknown, or stub-pointing tags.
- **Queue A (Difficulty, section 1.8): 18/18 non-stub instances.** 15 files, several instances split across 2-3 tests (e.g. `risk_class_high_at_exact_55_00_score` x3).
- **Queue B (Corner, section 1.9): 60/60 non-stub instances** — entities 11, state_machines 11, calculations 8, validations 7, endpoints 4, errors 12, rbac 4, cross-cutting 2, consistency 1. The 16 excluded stubs were not translated.
- **SKIPPED instances: none.** Every non-stub instance passed the PRD-first filter.

## Three PRD-first corrections (asserted the PRD-derived outcome, not the design's)

1. `Corner/rbac/each_role_performs_its_own_declared_operations` — design asserts the parcel is `NON_COMPLIANT` after the void; section 3.6 uniquely derives `PENDING_INSPECTION` (count 0, no passing inspection). Test asserts `PENDING_INSPECTION`.
2. `Corner/rbac/property_owner_cannot_extend_another_parcels_notice` — the design's cross-owner *list* 403 was omitted: section 2.1's ownership check guards twelve named operations and listing is not one of them.
3. `Corner/cross-cutting complexity layers/stale_program_version_blocked_enrollment` retry values — design says award 27000 / budget 353000, which implies a MODERATE match rate, but both parcels in its own setup are the HIGH profile (63.83). Section 3.8 uniquely derives 60000 x 0.60 = 36000, bonus_pct 0.15, hardship 0, budget 344000, version 3. Test asserts those.

Also omitted: the endpoints instance's "no DELETE verb" assertion (the PRD declares no verb, so no status is derivable).

## Verification

- `python3 -m py_compile` over all 34 emitted `.py` files: **ALL_FILES_COMPILE** (`__pycache__` cleaned up afterwards).
- Import audit clean: no unused imports and no undefined helper names in any file (remaining flags are client method/attribute names, i.e. tool false positives). Fixed this pass: removed dead imports in test_01/test_03/test_04/test_13 and restored `validate_success` in test_04.
- Every `PRD:` quote in all 24 test files re-verified as a verbatim, whole-sentence substring of `workspace/PRD.md` after ASCII folding: `checked; 0 bad`.
- All files ASCII-only (0 non-ASCII lines).

**Orchestrator verification:** independently confirmed 24 test files at the task root (`find workspace -type d -name test_suite -o -name test_helpers` returns nothing — no stray copies under `workspace/`, the known Step-5 failure mode), 98 `def test` functions and 98 `Design:` tags. Cleared all `__pycache__` trees before Step 7.

## Step 8: Finalize PRD — 2026-09-04T01:21:00.000Z

Done. `PRD_FINALIZED.md` created with exactly one targeted edit.

**Line counts:** PRD.md 525 lines / PRD_FINALIZED.md 525 lines — 0% line delta (one line revised in place, +1 sentence).

**Change:**
- section 3.8 Compliance-Support Programs and Cost-Share Awards (line 366, admission paragraph) — *insert* — pinned the initial value of `reimbursed_cents` on a newly created enrollment to integer `0` (not null) for every `program_type`, and stated it stays 0 until a reimbursement writes to it — `workspace/implementation/routes/support.py:141` (init) and `:200` (REIMBURSED write).

**Pre-edit search log (edit 1, the only edit):**
- (a) **Subject:** the `reimbursed_cents` field on `SupportEnrollment` — its initial value and every mutation of it.
- (b) **Impl paths enumerated:** repo-wide grep for `reimburs` across `implementation/**/*.py` returned exactly three hits: `routes/support.py:141` (the single enrollment `insert(db.enrollments, ...)` field dict — `"reimbursed_cents": 0`, unconditional, outside the `is_grant` branch so it applies to `CHIPPER_DAY`/`CURBSIDE_COLLECTION` too), `routes/support.py:198` (comment), `routes/support.py:200` (`enrollment["reimbursed_cents"] = enrollment["award_cents"]`, only on the `attended and COST_SHARE_GRANT` -> `REIMBURSED` branch). Also grepped every enrollment write path (`db.enrollments` / `db.enrollments.values()`) to confirm no second creation site and no other mutator: `routes/support.py:145` is the only insert; `routes/support.py:177` (list), `domain.py:70` (`program_enrollments`), `domain.py:127` (cycle-advance waitlist promotion), `routes/abatement.py:201` (read-only scan) never touch the field. Read `complete_enrollment` (COMPLETED / REIMBURSED / NO_SHOW fork), `cancel_enrollment` (APPROVED and WAITLISTED branches), and the non-grant award block (which nulls `award_before_bonus_cents`, `bonus_pct`, `hardship_bonus_cents`, `award_cents` but not `reimbursed_cents`) — none of them write or reset `reimbursed_cents`.
- (c) **Wording adjustment:** wrote "for every `program_type`, grant or not" rather than scoping to grants, because the `0` init sits outside the `is_grant` branch (a chipper-day enrollment also reads back 0, which the narrower wording would have mis-described); and wrote "stays 0 until a reimbursement writes to it" rather than "is only ever changed on completion", so the sentence stays true on the COMPLETED, NO_SHOW, CANCELLED and waitlist-promotion paths that leave it untouched, and remains consistent with the existing line 373 REIMBURSED write which was left verbatim.

No other PRD text was altered. The non-grant field-nulling list at line 364 omits `hardship_bonus_cents` (impl nulls it) — a real PRD silence, but outside the `<step_7_diff>` scope, so it was deliberately left alone.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (366) — the appended `reimbursed_cents` sentence — and nothing else. 115,655 -> 115,846 bytes, both 525 lines. The `hardship_bonus_cents` silence the subagent flagged as out-of-scope is left for Step 9's full scan to pick up.

## Step 9: Complete PRD — 2026-09-04T02:05:00.000Z

**Orchestrator decision:** Step 9 was deliberately run as THREE SEQUENTIAL FILE-PARTITIONED PASSES over `implementation/` rather than one single-shot scan. A single subagent asked to walk 3,013 lines of implementation against a 525-line/116 KB PRD reliably degrades into a shallow skim and returns a `PRD_COMPLETED.md` byte-identical to its source — the scan silently never happens. Partitioning bounds each pass's reading surface so the exhaustive walk is actually feasible, and each pass edits the same `PRD_COMPLETED.md` in place. Passes were ordered so the shared infrastructure (envelope, pagination, FK resolution, auth) is pinned first, then the dense calculation/cascade core, then the remaining routers. Every pass carried the NO-NEW-MISMATCH rule with a mandatory repo-wide grep per edit, including across the files assigned to the other passes.

Partition:
- **Pass A** — `app.py`, `auth.py`, `db.py`, `errors.py`, `response.py`, `validate.py`, `routes/{clock,cycles,communities,parcels,people}.py` (11 files). Also performed Step 9's step 0 (`cp PRD_FINALIZED.md PRD_COMPLETED.md`).
- **Pass B** — `calc.py`, `domain.py`, `routes/{inspections,findings,notices}.py` (5 files).
- **Pass C** — `routes/{abatement,support,certificates}.py` (3 files) + whole-document integrity check.

Totals: **52 edits across 47 changed lines** — Pass A 20 (18 ambiguity-pins, 2 mismatch-revisions), Pass B 18 (11 pins, 7 mismatches), Pass C 14 (12 pins, 2 mismatches). Aggregate: **41 ambiguity-pins, 11 mismatch-revisions**. All in-paragraph line replacements: 525 lines in, 525 lines out, zero sections added/renamed/moved, zero lines inserted or deleted.

### Pass A — infrastructure + clock/cycles/communities/parcels/people (20 edits)

- **section 2.2 (envelope)** — insert — ambiguity — `api_request_timestamp` is the one value read from real wall time, not the logical clock; no domain rule reads it — `response.py:38`
- **section 2.3 (pagination)** — insert — ambiguity — a `limit`/`offset` that doesn't parse as a base-10 integer is also `ERR_INVALID_REQUEST` — `validate.py:196-209`
- **section 2.3 (ordering)** — insert — ambiguity — equal `created_at` (routine, since the clock is frozen) is tie-broken by insertion order — `db.py:72-74`
- **section 2.4 (timestamps)** — insert — ambiguity — the EOD class is exactly `deadline_utc`/`invoice_due_utc`/`expires_at_utc`, serialised as `...T23:59:59Z` with no fractional component — `response.py:16,25-28`
- **section 2.6 (FK resolution)** — insert — ambiguity — a wrong-JSON-type FK fails as not-found (404), while an explicit `null` FK is skipped here and falls to request-shape — `validate.py:36-41`
- **section 2.7 (precision)** — insert — ambiguity — decimals are emitted as JSON numbers, so `risk_score` 67.50 transmits as `67.5` — `response.py:45-46`
- **section 2.9 rung 5** — insert — ambiguity — integer fields accept integral JSON floats (`2020.0`->`2020`) but never booleans; a datetime lacking `Z`/offset is read as UTC — `validate.py:107-114,160-172`
- **section 3.1 (activation)** — insert — ambiguity — the `PLANNING` precondition is tested before the already-active sweep, so a CLOSED/ACTIVE target answers `ERR_INVALID_STATE` — `routes/cycles.py:47-51`
- **section 3.1 step 4** — insert — ambiguity — waitlist renumbering rewrites `waitlist_position` alone and does not advance `version`/`updated_at` — `domain.py:137-142`
- **section 3.1 step 6** — insert — ambiguity — communities walked in `created_at` order, and the write is conditional: an unchanged rate leaves the community entirely untouched — `domain.py:200-205`, `routes/cycles.py:117-119`
- **section 3.1 (priority queue)** — insert — ambiguity — null-rank parcels sort *after* ranked ones, ordered by `created_at`; `cycle_id` must resolve but does not filter and need not be ACTIVE — `routes/cycles.py:170-185`
- **section 3.2 (compliance_status)** — revise — **mismatch** — intake initialises to `EXEMPT`, not `PENDING_INSPECTION`, when `exemption_flag` is true — `routes/parcels.py:79`
- **section 3.2 (updating a parcel)** — insert — ambiguity — clearing `exemption_flag` is asymmetrical: `compliance_status` stays `EXEMPT` and rank stays null until a later recompute — `routes/parcels.py:152-155`
- **section 3.6 (discretionary)** — insert — ambiguity — severity falls back to `CRITICAL` when the cited inspection's `max_deficiency_severity` is null or `NONE` — `routes/parcels.py:189-191`
- **section 3.6 (supersession)** — insert — ambiguity — several open notices are reachable (a failing inspection's citation supersedes nothing); all are voided and `supersedes_notice_id` records the newest — `domain.py:296-304`, `routes/inspections.py:329`
- **section 3.7 (contractor roster)** — insert — ambiguity — every PATCH field optional, an empty PATCH still bumps `version`; pricing reads the contractor's rate at verification time — `routes/people.py:84-94`, `routes/abatement.py:205-206`
- **section 3.9 (certification decision)** — insert — ambiguity — the `note` is validated but never persisted (no community note field) — `routes/communities.py:91`
- **section 3.9 (reopen)** — insert — ambiguity — reopening clears only `parcels_outreached_count`; rate, `certified_at_utc` and `lapse_count` survive — `routes/communities.py:115-119`
- **section 4 (table preamble)** — insert — ambiguity — list filters are plain equality, never existence- or enum-validated (only `supersedes_notice_id` 404s) — `routes/parcels.py:101-110` vs `routes/notices.py:31-33`
- **section 4 (POST /parcels row)** — revise — **mismatch** — the row omitted `exemption_flag` from the accepted optional fields — `routes/parcels.py:56`

Pass A walk log: **app.py** — blueprints, `g.touched`, ApiError/404/405/500 handlers, `strict_slashes=False`; no edits (no declared route reaches the 404/405 mapping). **auth.py** — rungs 1-2, `own`, `owner_must_match` (PropertyOwner-only); no edits, sections 2.1/2.9 pin all of it. **db.py** — `CLOCK_EPOCH` 2026-08-01, empty boot, audit vs evidence insert shape, `_seq`, `sort_created`; produced the 2.3 tie-break. **errors.py** — all 48 id->status entries diffed against the section 5 table, exact match; no edits. **response.py** — `fmt_dt`/`fmt_eod`, `EOD_FIELDS`, `request_id`, `meta`, Decimal->float, `_`-stripping, `ok`/`created`/`ok_list`, `touch` dedupe; produced 2.2/2.4/2.7. **validate.py** — `FK_ORDER`, null/type handling, all `get_*` coercions, `get_half_hours`, `parse_dt`, `check_window`, `pagination`; produced 2.6/2.9-rung-5/2.3. **routes/clock.py** — no edits, 2.5 pins it exactly. **routes/cycles.py** — create defaults, activate ordering, all 8 advance steps, close guard, queue sort; 4 pins. **routes/communities.py** — create, thresholds, certify/defer, reopen; 2 pins. **routes/parcels.py** — create ordering/defaults/intake scoring, filters, PATCH, survival outcome, discretionary notice, certificate intake; 5 edits incl. both mismatches. **routes/people.py** — inspector + contractor create/read/PATCH; 1 pin.

### Pass B — calc.py, domain.py, inspections/findings/notices (18 edits)

- **section 3.2** — revise — mismatch — "`risk_score` is a 0-to-100 figure" -> "a figure normally lying between 0 and 100" — `calc.py:127`
- **section 3.2** — insert — mismatch — the clamp is one-sided: `min(100, ...)` with no floor at zero, so a large hardening credit yields a genuinely negative score (verified: `-17.50`, bands `LOW`) — `calc.py:115-127`
- **section 3.2** — insert — ambiguity — the `POST_INSPECTION_VERIFIED` basis is sticky; a later rescore reuses the carried-forward veg subscore and hardening credit, re-reading only slope/roof/access/hazard — `domain.py:172-182`
- **section 3.2** — revise — mismatch — priority rank has a *fifth* key: `created_at` ascending then insertion order per 2.3, not a "fourth and final" key; `id` is still never consulted — `domain.py:236-249`
- **section 3.3** — insert — mismatch — inspector `assigned_open_count` is maintained with no audit bump and there is no inspector-update endpoint, so an inspector's `version` stays 1 for life — `inspections.py:95,175,203,218,310`
- **section 3.3** — revise — ambiguity — a booked inspection also holds `measured_veg_points`, `hardening_credit_points`, `max_deficiency_severity` and `completed_at_utc` null — `inspections.py:90-93`
- **section 3.4** — insert — ambiguity — notice lead time is `floor(seconds/86400)` whole days: 9d23h counts as 9; a past start is refused even at a lead of 0; a start exactly on the clock counts as 0 and clears a floor of 0 — `inspections.py:129-131`
- **section 3.4** — insert — ambiguity — access-denial `reason_code` is required *and* non-blank, unlike the free-text `reason` fields elsewhere which accept `""` — `inspections.py:151`
- **section 3.5** — insert — ambiguity — zone evaluations and hardening findings carry no from-state precondition on the parent inspection — `inspections.py:222-270`
- **section 3.5** — insert — ambiguity — `deficit_ratio` divides the already-rounded `deficit_ft` by `required_clearance_ft`; `measured_clearance_ft` has no place limit (verified: 20.375 ft -> `0.3200`, not `0.3208`) — `calc.py:153-156`
- **section 3.5** — insert — mismatch — the failing branch's posture write is unconditional and *not* symmetrical with the passing branch: an exempt parcel that fails is driven to `NON_COMPLIANT` — `inspections.py:326`
- **section 3.5** — revise — mismatch — the community is dropped from the unconditional `version`-bump list; its `version`/`updated_at` advance only when `compliance_rate_pct` actually moved or when it lapsed — `domain.py:200-215`
- **section 3.6** — revise — ambiguity — voiding's "recomputed" posture spelled out as the full fixed five-rung ladder (`EXEMPT` -> `ABATEMENT_PENDING` -> `NON_COMPLIANT` -> `COMPLIANT` -> `PENDING_INSPECTION`), scoped to the two call sites that actually derive it — `domain.py:146-169`
- **section 3.6** — insert — ambiguity — the lapsed-deadline refusal is evaluated ahead of the extension ceiling, so a notice both `EXTENDED` and past deadline answers `ERR_INVALID_STATE` — `notices.py:53-59`
- **section 3.7** — revise — ambiguity — verification link 4 uses the same ladder with `verified_clear`, so an emptied notice set yields `COMPLIANT` without a passing inspection and `PENDING_INSPECTION` is unreachable there — `domain.py:164-165`
- **section 3.7** — revise — ambiguity — the `AUTHORIZED` order's null list extended with `verified_by_inspector_id`, `actual_crew_hours`, `green_waste_tons`, `invoice_due_utc`, `cancel_reason` — `notices.py:107-131`
- **section 2.6** — insert — ambiguity — the `supersedes_notice_id` filter-existence check sits *below* pagination screening, so a bad `limit` plus an unknown filter id answers `ERR_INVALID_REQUEST` — `notices.py:29-33`
- **section 4 (row 440)** — revise — mismatch — `violation_notice_method` is optional, defaulting to `CERTIFIED_MAIL` on the failing branch, not required — `inspections.py:280,329`

Pass B walk log: **calc.py** (311 lines, read end to end) — all 7 calculations, every constant, every `rhu` site, both ladder saturations, `end_of_day`, `allocate_payment` bucket order; 3 edits (one-sided risk clamp x2, pre-rounded `deficit_ratio`); `notice_dates` ceil/floor, cost-recovery buckets and `cost_share_award` were already fully pinned. **domain.py** (338 lines, end to end) — posture derivation, `rescore_parcel`, `recompute_community`, `recompute_priority_ranks`, `issue_notice`, `revoke_certificates`, all five `recount_*` helpers, `renumber_waitlist`, `staleness_days`, `require_active_cycle`; 5 edits. **routes/inspections.py** (333 lines, end to end) — booking, serve-notice lead time, access denial, zone/finding creation, both completion branches, all `recount_inspector_load` sites; 6 edits + the section 4 row. **routes/findings.py** (60 lines, end to end) — pure read/list surface; 0 edits. **routes/notices.py** (139 lines, end to end) — read/list, extend, void, authorize-abatement; 3 edits.

Pass B deliberately skipped as unobservable: `staleness_days` negative floor division, `require_active_cycle`'s None branch, `bonus_pct` when hardship is false, access-denial guard ordering (logically equivalent conditions), zone-coverage vs result-agreement ordering (same error id), `ERR_NOTICE_NOT_OVERDUE` vs live-order `ERR_INVALID_STATE` (unreachable state combination). Two draft claims were weakened by the no-new-mismatch grep — a "the one conserved quantity without an audit bump" superlative (falsified by `renumber_waitlist`) and a blanket "every place this document says recomputed" (falsified by the direct posture assignments in the pass/fail/cancel/discretionary paths).

### Pass C — abatement/support/certificates (14 edits)

- **section 3.7 Awarding** — insert — ambiguity — the four award eligibility tests are evaluated in section 2.9 ladder order (rung 21 window -> rung 22 licence/insurance -> rung 24 capacity), not in the order narrated, and `ERR_CONTRACTOR_NOT_LICENSED` precedes `ERR_CONTRACTOR_INSURANCE_LAPSED` inside rung 22; also that no bound of the window is compared to the clock at award — `routes/abatement.py:85-112`
- **section 3.7 Reporting the work done** — insert — ambiguity — an `AUTHORIZED` order's null `contractor_id` matches nobody, so a contractor hits `ERR_NOT_RESOURCE_OWNER` at rung 4 before the state gate — `routes/abatement.py:158-165`
- **section 3.7 Reporting the work done** — insert — ambiguity — the pre-`work_start_utc` refusal is reported as `ERR_INVALID_STATE` — `routes/abatement.py:166-167`
- **section 3.7 Cancelling** — insert — ambiguity — the parcel posture write is unconditional, not a re-derivation through section 3.6: an exempt parcel and a parcel still holding a second `ABATEMENT_AUTHORIZED` notice both land on `NON_COMPLIANT` — `routes/abatement.py:143-147`
- **section 3.7 Cost Recovery** — insert — ambiguity — `verified_note` is validated as a string but never persisted (no note field on the order) — `routes/abatement.py:180`
- **section 3.7 Cost Recovery** — insert — ambiguity — the inspector-standing gate is a roster lookup on `X-User-ID`; an id matching no registered inspector passes, and verification has no ownership rung — `routes/abatement.py:183-185`
- **section 3.7 step 7** — insert — ambiguity — "governing cycle" for `invoice_due_utc` is the cycle on the *substantiating inspection*, not whichever cycle is currently `ACTIVE` — `routes/abatement.py:212-214`
- **section 3.7 Liens** — revise — **mismatch** — the section 2.10 identity does not survive a post-filing payment: `lien_amount_cents` is stamped once and never rewritten, so `paid_cents + lien_amount_cents` can exceed `total_recoverable_cents` — `routes/abatement.py:246-266` (+ `routes/cycles.py:81-87`)
- **section 3.8 enrolling** — insert — ambiguity — `vendor_invoice_cents` may be 0 but may not be negative — `routes/support.py:91`
- **section 3.8 award sizing** — revise — **mismatch** — the non-grant null list omitted `hardship_bonus_cents`; it is null (not 0) even when `owner_hardship_flag` is true [the Step 8 lead, confirmed] — `routes/support.py:128-133`
- **section 3.8 Admission** — insert — ambiguity — in-request admission is not a mutation: a created enrollment is returned with `version` 1 — `routes/support.py:145-163`
- **section 3.8 Cancelling** — insert — ambiguity — waitlist renumbering after a `WAITLISTED` cancel bumps no peer's `version`/`updated_at` (mirrors section 3.1 step 4) — `routes/support.py:233`, `domain.py:137-142`
- **section 3.9 certificate decision** — insert — ambiguity — the optional `note` is stored as `decision_note` on the `ISSUE` branch too, and stays null when omitted — `routes/certificates.py:69-70`
- **section 3.9 certificate decision** — insert — ambiguity — no uniqueness test: a parcel may hold several requests and more than one simultaneously `ISSUED` certificate — `routes/certificates.py:42-75`

Pass C walk log: **routes/abatement.py** (287 lines, read in full) — order lookup/404; `read_order` 4-role set with no ownership rung and `list_orders` 3-role set + 4 filters + `created_at` ordering; award (FK->shape->window->state->rung 21->22->24, closed-window intersection, `start < insurance_expiry`, aggregate-per-UTC-date capacity, `recount_contractor_commitment`); cancel (both from-states, notice->`OVERDUE`, flat `NON_COMPLIANT`, conditional contractor unwind, community cascade); complete-work (ownership before shape, half-hour hours, 2-place tonnage, clock gate); verify-completion (state->standing->SoD, voluntary-precompliance detection over `RESERVING_ENROLLMENT_STATUSES` with `created_at <` `issued_at_utc`, all 7 invoice steps and both variants, `invoice_due_days` from the substantiating cycle with the 45 fallback, 5-link cascade); payments (owner match via the notice's parcel, `amount_cents >= 1`, outstanding ceiling, four-bucket waterfall with the subsidy shortfall in `LABOR`, `audit=False` evidence shape, `INVOICED -> PAID` only on exact settlement); payment reads/lists. **routes/support.py** (234 lines, read in full) — program creation (FK order, `budget_total >= 0`, `capacity_slots >= 1`, window orientation, rung-11 cycle activity, init counters); program reads/lists; enrollment creation walked rung by rung (parcel before program per 2.6, ownership, `expected_program_version`, rung 7 invoice presence both ways, rung 9 staleness, rung 10 duplicate over `LIVE_ENROLLMENT_STATUSES`, rung 11, rung 12 half-open window, rung 26 cap `>` 1,000,000, award sizing, in-request admission both branches, waitlist numbering, `reimbursed_cents` 0); complete (three forks, reservation retained on `REIMBURSED`, slot+budget restored on `NO_SHOW`); cancel (both from-states, exact compensation, renumbering). **routes/certificates.py** (75 lines, read in full) — reads/lists (4-role set, 3 filters, no ownership rung); decision (state gate, `PENDING_INSPECTION` -> `ERR_PARCEL_NOT_INSPECTED` ahead of the posture/open-notice test -> `ERR_OPEN_VIOLATION_EXISTS`, 90-day end-of-day expiry, the two snapshots, `DENY` with no posture precondition, `version` +1 on both branches).

### Final integrity verification (orchestrator, independent of the subagents)

```
   525 115655 PRD.md
   525 115846 PRD_FINALIZED.md
   525 131672 PRD_COMPLETED.md
changed lines vs PRD_FINALIZED: 47
cmp PRD_FINALIZED.md PRD_COMPLETED.md: differs (good — the scan actually ran; a byte-identical
  PRD_COMPLETED.md is the known silent-no-op failure mode and was explicitly checked for)
diff of heading lists (line number + text, ^#{1,4}): empty -> headings identical, no section
  added, renamed, moved or reordered
tail: file ends at the completed section 5 error table (`ERR_PAYMENT_EXCEEDS_OUTSTANDING | 422`), not mid-sentence
```

`PRD_COMPLETED.md` is +15,826 chars over `PRD_FINALIZED.md` (+13.7%) across 47 in-place line replacements, with the line count and section structure preserved exactly. `implementation/` was not modified in Step 8 or Step 9, so the Step 7 evidence stands unchanged: all 8 `results.{1..8}.json` on disk report 98/98 passed, 0 failed, 0 errors, 0 skipped.

**PIPELINE COMPLETE** — Steps 1-9 all finished; `workspace/PRD_COMPLETED.md` written.
