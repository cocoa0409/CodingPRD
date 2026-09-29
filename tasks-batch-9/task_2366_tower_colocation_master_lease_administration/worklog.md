# Worklog — task_2366_tower_colocation_master_lease_administration

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2366_tower_colocation_master_lease_administration/` and `tasks/task_2366_tower_colocation_master_lease_administration/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T06:04:00.000Z

All three artifacts are complete and the lint is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2366_tower_colocation_master_lease_administration/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2366_tower_colocation_master_lease_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2366_tower_colocation_master_lease_administration/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     90
  Calls scanned (§1.8+§1.9):  1284

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

Directory: `/home/ubuntu/github/CodingPRD/tasks/task_2366_tower_colocation_master_lease_administration/`

**SCAFFOLD.yaml** (§1.0–§1.7, neither design key present) — `domain_name: tower-colocation-master-lease`, `api_prefix: /tower-colo`, `difficulty_level: beyond_expert`, `entity_topology: graph`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`, complexity layers = optimistic_concurrency + cascading_side_effects + dual_variant_calculation + derived_field_reconciliation.
- 14 entities, 8 state machines, 2 concurrency rules (stale-Tower on analysis create, stale-Project on cost-share reallocate)
- 12 calculations (elevation-tiered load units, dual-variant structural analysis, per-anniversary escalators with a 150% cap, modification-cost pipeline with pinned volume-discount tier, retroactive unauthorized-install billing, capacity reconciliation/posture, SLA credits)
- 38 ordered validations, 63 endpoints, 58 error codes, 5 roles (PortfolioAdmin, StructuralEngineer, ComplianceAuditor, Tenant→entity-backed, Landlord→entity-backed)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 rule_ids / **25 instances**: dual_variant_calc 2, combinatorial_formula 3 (modes a/b/c), non_linear_state_machine 3, transitive_cascade 3 (incl. a depth-4 audit-finalization cascade), priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 2.

**SCAFFOLD_CORNER_DESIGN.yaml** — 9 sections / **115 instances** (90 full recipes + 25 `excluded_because` stubs, every citation resolving to a real §1.8 instance name): entities 15, state_machines 22, calculations 19, validations 30, endpoints 7, errors 7, rbac 7, cross_cutting_complexity_layers 7, consistency_model 1.

Verified beyond the lint: no duplicate instance names across the two design files, no stub carries a `test_recipe`, every `excluded_because.difficulty_instance` exists in §1.8, and no forbidden concurrency vocabulary ("simultaneously", "in parallel", "first-writer-wins", "race winner/loser") appears anywhere in the task. All 58 catalog errors are now reachable from at least one instance, including the two 412 OCC codes, the four invalid-state codes, the segregation-of-duties 403 and the ground-space 422. The sibling-task constraint was honored throughout — nothing under `tasks/` other than this task directory was listed, read, or grepped.

## Step 3: Copy shared files — 2026-09-02T06:05:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_2366_tower_colocation_master_lease_administration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T06:22:00.000Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2366_tower_colocation_master_lease_administration/workspace/PRD.md` — **487 lines**, ends at §5 with no audit footer.

**Sections (26 headings):**
- §1 Introduction
- §2 Global Specifications — 12 subsections: 2.1 RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Common Resource Properties, Logical Clock & Time-Driven Expiry · 2.5 Path/Body Resource Resolution · 2.6 Validation Precedence (full 38-rule ladder) · 2.7 Tower Capacity Reconciliation · 2.8 The Capacity Posture Gate · 2.9 Parallel Status Axes & Cascade Discipline · 2.10 Precision and Rounding · 2.11 Optimistic Concurrency · 2.12 Tenant Receivables & Arrears Interlock
- §3 Business Logic — 9 subsections: site inventory · ground rent (escalation/renewal/buyout/remittance) · carrier onboarding & receivables · application filing & equipment costing · structural review & dual-variant analysis · reinforcement projects & cost sharing · amendment papering/execution/supersede · departure & capacity release · compliance audits & retroactive billing
- §4 Endpoint Definitions (63 rows, 4 columns)
- §5 Error Code Catalogue (58 rows, 2 columns)

**Hard Contract 1 — Field-Name Coverage: PASS.** 123 required identifiers (114 entity fields + endpoint `input` identifiers + 9 computed-response members `occupied_band_count`, `capacity_hold_application_count`, `current_utc`, `expired_ground_lease_count`, `expired_master_lease_count`, `frozen_tower_count`, `amendment_id`, `bottom_ft`, `top_ft`). Missing after verification: **0**.

**Hard Contract 2 — Rule Coverage: PASS.** All 8 categories walked programmatically against SCAFFOLD.yaml: 8 state machines / **60 transitions** all present in explicit `FROM → TO` arrow form (0 missing) with all states named; 12 calculations — every target field and every pinned rounding order in prose (0 missing); 38 validations — all error IDs present in §2/§3 body, in the scaffold's priority order (0 missing); 2 concurrency rules — `expected_tower_version`/`ERR_STALE_TOWER_VERSION` and `expected_modification_project_version`/`ERR_STALE_PROJECT_VERSION` both specified with parent-version semantics; 58 catalogue errors with **0 status-code mismatches**; 63 endpoints with **0 missing rows and 0 role mismatches**; all enum values across all entities present (0 missing); all 5 roles present.

**Hard Contract 3 — §3 Path Purity: PASS.** §3 spans lines 207–354 with 852 backticked tokens; **0 violations** (no `/`-prefixed token, no bare HTTP method, no method+path combo).

Also verified: §2.2 matches `section-2.2-response-structure.md` byte-for-byte; zero forbidden concurrency vocabulary ("simultaneously", "in parallel", "first-writer-wins", "race winner/loser"); no fuzzy quantifiers or pseudocode operators.

**Two things to flag:**

1. **Scaffold gap:** `ELEVATION_SEPARATION_BUFFER_FT` is referenced by validation priority 18 and by `ERR_ELEVATION_BAND_CONFLICT`, but its numeric value is defined nowhere in SCAFFOLD.yaml (confirmed by two greps plus `worklog.md`). I stated **10 feet** in §3.7. If the withheld design files pin a different value, §3.7's band-separation paragraph needs a one-word edit.

2. **Scaffold inconsistency reconciled:** the application-revise state machine precondition requires `tower.capacity_posture == OPEN`, while validation priority 14 only checks `!= FROZEN`. §3.5 states revision requires `OPEN` and that both `RESTRICTED` and `FROZEN` block it carrying `ERR_TOWER_POSTURE_FROZEN`.

Both withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or grepped, and no sibling task directory under `tasks/` was read.

## Step 5: Generate unit tests — 2026-09-02T06:55:00.000Z

Suite complete and audited.

## Files written

**Stage 1 — `test_helpers/`** (9 modules): `constants.py`, `api_errors.py` (58 error ids + the §5 status map registered with the framework), `types.py`, `api_client.py` (~60 endpoint methods over `GenericApiClient`), `factories.py`, `assertions.py`, `test_users.py`, `fixtures.py` (API-driven state builders, staged colocation chain, project/audit/delinquency helpers), `__init__.py`.

**Stage 2 — `test_suite/`**: `conftest.py` plus 13 test modules, **173 tests total**, all collecting with zero errors.

| Queue | File | Tests |
|---|---|---|
| A | test_01_structural_dual_variant_and_pinned_formulas | 14 |
| A | test_02_lifecycle_cycles_and_transitive_cascades | 19 |
| A | test_03_validation_precedence_and_boundary_precision | 12 |
| A | test_04_cross_entity_dependencies_overlaps_and_invariants | 20 |
| B | test_10_resource_shapes_and_field_contracts | 18 |
| B | test_11_application_and_amendment_transitions | 11 |
| B | test_12_expiry_sweeps_audits_and_certification | 8 |
| B | test_13_load_rent_and_billing_calculations | 14 |
| B | test_14_identity_scope_and_submit_validations | 13 |
| B | test_15_term_renewal_and_fiscal_validations | 16 |
| B | test_16_endpoint_surface_and_error_codes | 12 |
| B | test_17_role_permissions | 9 |
| B | test_18_concurrency_and_derived_field_reconciliation | 7 |

Queue A (depth): **65 tests**. Queue B (breadth): **108 tests**.

## Coverage audit (scripted against both design indices)

- **Depth: 25/25 instances, every one with >=2 tests.** None skipped.
- **Breadth: 89/90 non-stub instances covered (>=1 test each).**
- **All 25 excluded stubs emitted no tests**, and all 25 of their `difficulty_instance` cross-references resolve to real depth instance names.
- Every test carries exactly one `Design:` line, as the final docstring line, pointing at an instance that exists; no untagged, dual-tagged or dangling tags.
- Every docstring's opening PRD quotation was verified as a character-for-character (whitespace-normalised) substring of `workspace/PRD.md`, each >=8 words.
- No `skip`/`skipif`/`xfail` anywhere; no scaffold references in any comment; no machinery words in test identifiers; no cross-task references. Pyflakes clean apart from the deliberate side-effect import in `conftest.py`.

## Single skipped instance

`Corner/validations/amendment_execute_rejected_without_pass_analysis` — its precondition (an application analysed at 96.0% / MODIFICATION_REQUIRED yet approved anyway) is not constructible under the PRD: §3.5 requires a CERTIFIED modification project on the newest non-superseded analysis before that approval, and papering an amendment requires APPROVED. The two routes to structural clearance are exactly the two things approval itself demands, so no PRD-legal path produces a DRAFT amendment lacking clearance. Left as a gap rather than weakened.

## Recipe-vs-PRD corrections applied silently

- `structure_type: "LATTICE"` replaced with `SELF_SUPPORT` wherever a recipe used it as valid input (PRD §3.1 admits only MONOPOLE/SELF_SUPPORT/GUYED); kept only in the instance that deliberately tests enum rejection.
- The elevation separation buffer is asserted at the PRD's **ten feet**, not the 2 ft one recipe describes; the asserted band-conflict outcome is unchanged.
- Timestamps are asserted as instants/prefixes rather than the recipes' bare `...T00:00:00Z` strings, since §2.4 renders three fractional digits.
- A handful of individual recipe assertions were dropped as PRD-undetermined rather than guessed: `CostShare.basis_load_units` (the PRD names that field on the beneficiary entry only), `Landlord.w9_on_file` and `rejection_reason` reads (no such published read surface), `allocated_cents` after a DECLINE, absolute tower version numbers, and `current_monthly_rent_cents` when the clock sits exactly on the effective date. Observable equivalents were asserted in their place.

## Step 6: Generate implementation — 2026-09-02T06:35:00.000Z

The implementation is complete and verified.

## Files written
`/home/ubuntu/github/CodingPRD/tasks/task_2366_tower_colocation_master_lease_administration/workspace/implementation/`

- `start.sh` (executable; installs Flask only if missing, `exec python3 app.py`, honours `$PORT`, default 10000)
- `requirements.txt`, `app.py` (Flask factory + `ApiError`/`HTTPException`/catch-all handlers)
- `db.py` (in-memory `Store` of 14 dicts, cold-start logical clock pinned to `2026-08-01T00:00:00Z`, **no seeding anywhere**), `util.py`, `calc.py`, `errors.py`, `response.py`, `middleware.py`, `find.py`, `serializers.py`, `services.py`
- `routes/__init__.py`, `routes/sites.py` (14), `routes/carriers.py` (19), `routes/structural.py` (15), `routes/amendments.py` (15)

## Endpoint count
**63 routes registered — an exact 1:1 match with the §4 table** (verified by enumerating `url_map`). Fresh-process boot over real HTTP confirmed: `POST /tower-colo/towers` -> 201, `GET /tower-colo/towers` -> 200.

## Verified behaviours (smoke runs)
Pinned arithmetic all lands: equipment load `(w+30*A)*q*elev_mult` = 712.5; MLA site rent 250000 @ 3.5% x 4 anniversaries = **286880**; ground rent simple escalation 100000 @ 3%/7y = 121000; 12-month landlord remittance across an anniversary = 1218000; project cost pipeline 20000000 -> discount 0.015, fee 2364000, total 22064000 with floor-allocated shares summing **exactly** to the total; retro billing 24 x 3013 x 1.5 = 108468. Also exercised: full application->analysis->approve->amendment->execute->notice->decommission arc, freeze on FUNDED plus promotion of the single `CAPACITY_HOLD` winner on certification, SoD rejection, construction-window conflict, band/space/term/delinquency ladders, both billing-axis error codes, clock sweeps (`expired_ground_lease_count`/`expired_master_lease_count`/`frozen_tower_count`), monotonic clock, pagination vs. shape errors, landlord scope and identity errors.

## PRD ambiguities resolved
1. **Timestamps** — `created_at`/`updated_at` use the logical clock; `api_request_timestamp` uses wall clock; `_seq` is the stable tiebreaker for every ordering rule. Calendar-date fields echo the caller's own raw string (server-computed dates render `YYYY-MM-DD`).
2. **Derived fields computed on read**, never stored (tower occupancy/posture, MLA privilege + executed count, tenant credit status, `allocated_cents`, audit totals, both `current_monthly_rent_cents`). `total_load_units` is stored but recomputed on every line mutation.
3. **Pagination vs. shape** — non-integer `limit`/`offset` -> `ERR_INVALID_REQUEST` (step 3); parseable but out of range -> `ERR_INVALID_PAGINATION` (step 4).
4. **`revise` treats RESTRICTED like FROZEN** (§3.5 requires posture `OPEN`); the other three posture-gated ops block only on `FROZEN`.
5. **`open-renewal`** checks window (24) before options (25), per the ladder rather than the §3.2 prose order.
6. **Landlord scope** applies only to the ground-lease *list* (the §2.1 eleven-op list is exhaustive) — single lease read and the payment list are unscoped.
7. **Billing axis** — an undeclared `(from, to)` pair -> `ERR_INVALID_BILLING_STATE`; a declared pair failing its `execution_status` precondition -> `ERR_INVALID_AMENDMENT_STATE`. `to_status` accepts all four enum members so undeclared-but-valid targets surface the state error, not a shape error.
8. **Superseded amendment on execute** -> `TERMINATED` + `restoration_status COMPLETE` + `billing_status CLOSED`, with `terminated_at` left null and no deposit release (§3.7 lists no such effect).
9. **`supersedes_amendment_id`** that doesn't exist -> `ERR_AMENDMENT_NOT_FOUND` (body FK, step 6); existing but wrong status/tower/MLA -> `ERR_SUPERSEDE_TARGET_INVALID` (step 31).
10. **Cost-share ladder** — allocation = window (22) -> beneficiaries (32) -> quotation (37); reallocation re-checks OCC -> state -> a `BILLED` share blocks (`ERR_INVALID_PROJECT_STATE`) -> beneficiaries. `certify-completion` = state -> SoD -> all non-VOIDED shares `BILLED`.
11. **SLA credit** latches once per application and only on the first analysis after the most recent review entry; credit = `round_half_up(mla.base_monthly_rent_cents x 0.25)` debited from the tenant balance.
12. **Audit finalization** groups findings by tenant and applies one balance adjustment per tenant, so the four-level delinquency cascade fires once each.
13. **`start-construction` before the window opens** -> `ERR_INVALID_PROJECT_STATE`; the future-date guard on `audit/start` is unreachable (step 29 is scoped to scheduling) but implemented as `ERR_AUDIT_DATE_IN_FUTURE`.
14. **Optional reason/note fields** (`rejection_reason`, `revision_note`, `decline_reason`, `cancellation_reason`) are accepted but not required; `restoration_confirmed` is required and must be `true`.

## Step 7: Run tests and iterate — 2026-09-02T13:15:00.000Z

All 8 parallel rounds passed on the first sweep — no fixes were needed.

## Summary

**Iterations run:** 1 (one full 8-round parallel stability sweep, all rounds launched concurrently under `setsid nohup` and joined with `wait`; no early exit).

**Sweep result — clean:**

| round | total | passed | failed | errors | skipped | duration |
|---|---|---|---|---|---|---|
| 1 | 173 | 173 | 0 | 0 | 0 | 1692 s |
| 2 | 173 | 173 | 0 | 0 | 0 | 1609 s |
| 3 | 173 | 173 | 0 | 0 | 0 | 1649 s |
| 4 | 173 | 173 | 0 | 0 | 0 | 1700 s |
| 5 | 173 | 173 | 0 | 0 | 0 | 1704 s |
| 6 | 173 | 173 | 0 | 0 | 0 | 1716 s |
| 7 | 173 | 173 | 0 | 0 | 0 | 1720 s |
| 8 | 173 | 173 | 0 | 0 | 0 | 1612 s |

Union of failing tests across all 8 rounds: **0**. No flakiness signal — every one of the 173 tests passed in every round, including the timing-sensitive ones (OCC stale-version checks on tower/project, per-test-server isolation boots, logical-clock expiry sweeps).

**Tests deleted:** none. The diagnostic protocol (STEP 0 → 3) was never entered, because STEP 0 produced an empty failing set.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `workspace/implementation/`:** none.

### Notes from reading the artifact while the sweep ran

- Storage is in-memory only (`workspace/implementation/db.py` — `Store.reset()` over plain dicts, `CLOCK_DEFAULT = 2026-08-01T00:00:00Z`, no file/SQLite/`/tmp` persistence), and nothing is seeded at boot, so the `per-test-server` isolation genuinely wipes all state per test. That is consistent with the cardinal rules.
- Two spots are stricter than the PRD strictly requires but do not currently cause divergence, so they were deliberately left alone (changing them would be gold-plating with no failing test to justify it):
  - `workspace/implementation/calc.py`, `allocate_shares()` — the remainder-recipient ranking inserts `basis_seq` between `basis_created_at` and `tenant_created_at`, whereas §3.7/§3.6 prose pins the order as `basis_created_at` → beneficiary tenant's `created_at` → `basis_load_units`. It only diverges if two beneficiaries share an identical `basis_created_at` instant, which the logical clock makes possible but which no test exercises.
  - `workspace/implementation/services.py`, `promote_if_open()` — appends `_seq` as a fourth tiebreaker after the three PRD-declared keys; a pure tie-break refinement, not a rule change.
- Derived counters (`open_review_count`, `reserved_load_units`, `available_ground_space_sqft`, `capacity_posture`) are recomputed as pure functions of the contributing set rather than incremented, which is exactly the §2.7 "conserved quantity" requirement — that is why the decommission/no-drift and freeze-pushback tests are stable rather than order-dependent.

Sweep artifacts at `workspace/implementation/results.1.json` … `results.8.json`, driver log at `workspace/sweep.log`.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T13:16:00.000Z

Skip condition met per skill spec: Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior the implementation exhibits at every site the test suite exercised, so there is no `<step_7_diff>` to hand off and no PRD silence for Step 8 to patch. No `PRD_FINALIZED.md` is produced; Step 9 starts from `workspace/PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T13:35:00.000Z

Done. Verified line-for-line in-paragraph edits only (no new sections, line count unchanged).

## Summary

**Source vs output:** `workspace/PRD.md` 486 lines / 94,277 chars → `workspace/PRD_COMPLETED.md` 486 lines / 105,688 chars (**+11,411 chars**, 45 lines rewritten in place, 0 lines added/removed).

**Counts:** 32 ambiguity-pins, 15 mismatch-revisions.

### Changes

- §2.1 RBAC — insert — ambiguity — blank/whitespace-only `X-User-ID` counts as absent for `ERR_UNAUTHENTICATED` — `middleware.py:24`
- §2.1 Scope — insert — ambiguity — no read or list outside the eleven ops is scoped (Tenant sees all rows); Landlord ground-lease list rejects a foreign `landlord_id` filter but silently narrows when omitted — `middleware.py:58`, `sites.py:177`
- §2.2 Success envelope — insert — ambiguity — `api_request_timestamp` is host wall clock, not the logical clock — `response.py:16`
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` text → `ERR_INVALID_REQUEST`, not `ERR_INVALID_PAGINATION` — `middleware.py:223`
- §2.3 Ordering — insert — ambiguity — all ties broken by server creation sequence; unknown identifier filters → empty page, unknown enum filters → `ERR_INVALID_REQUEST` — `db.py:86`, `middleware.py:204`
- §2.4 Common properties — insert — ambiguity — calendar-date fields echo the caller's own raw rendering — `serializers.py:6`
- §2.4 Logical clock — insert — ambiguity — `frozen_tower_count` = towers newly `FROZEN` by this sweep only — `sites.py:380`
- §2.6 #11 — revise — mismatch — `ERR_MLA_NOT_ACTIVE` also carries master-lease activate/reinstate state rejections; `ERR_INVALID_LEASE_STATE` reserved for ground leases — `carriers.py:127,142`
- §2.6 #34 — revise — mismatch — `ERR_TENANT_DELINQUENT` applies to four operations, adding master-lease reinstatement — `carriers.py:146`
- §2.9 Cascade discipline — revise — mismatch — tower `version` untouched where not explicitly called out (submit/revise/approve/reject/withdraw/allocate/decline/void/notice/finalize/MLA sweep) — `carriers.py:343`, `amendments.py:264`
- §2.12 MLA counters — revise — mismatch — `executed_amendment_count`/`application_privilege` are read-derived; amendment execution does not bump the MLA — `services.py:232`, `amendments.py:230`
- §3.1 Landlord — insert — ambiguity — `remit_contact_email` non-blank, ≤320 chars — `sites.py:117`
- §3.2 Ground rent — revise — mismatch — anniversary count is 0 before the first anniversary; 29 Feb collapses to 28 Feb — `util.py:103,111`
- §3.2 Renewal — revise — mismatch — state check first, then window, then option count — `sites.py:204`
- §3.2 Remittance — insert — ambiguity — `period_end_date` must exceed start → `ERR_INVALID_REQUEST` before lease resolution — `sites.py:278`
- §3.2 Payment list — revise — mismatch — no landlord ownership check on the payment list — `sites.py:322`
- §3.3 Tenant — insert — ambiguity — `carrier_code` collision → `ERR_INVALID_REQUEST` — `carriers.py:59`
- §3.3 Tenant payment — insert — ambiguity — response is the updated Tenant resource; no payment entity persists — `carriers.py:89`
- §3.3 Activation — revise — mismatch — non-DRAFT → `ERR_MLA_NOT_ACTIVE`; stale `expires_on` → `ERR_INVALID_REQUEST` — `carriers.py:126-131`
- §3.3 Reinstatement — revise — mismatch — state checked before credit; delinquency → `ERR_TENANT_DELINQUENT` (402) — `carriers.py:141-147`
- §3.4 Equipment lines — insert — ambiguity — adding a line is not state-gated and immediately recomputes `total_load_units` and bumps the application — `carriers.py:259`
- §3.5 Analysis — insert — ambiguity — resource publishes `base_load_units`, `subject_load_units`, `pipeline_load_units` — `serializers.py:183`
- §3.5 SLA latch — revise — mismatch — settled on every analysis creation before the result branch; null deadline cannot breach — `structural.py:176-186`
- §3.5 Revision — insert — ambiguity — `revision_note` ≤500 chars, retained when omitted — `carriers.py:351`
- §3.5 Rejection — revise — mismatch — `rejection_reason` optional, ≤500 chars — `carriers.py:425`
- §3.5 Promotion — revise — mismatch — only decommission, certification and **FUNDED** cancellation promote — `structural.py:436`
- §3.6 Proposal — insert — ambiguity — pipeline outputs and audit fields null at `PROPOSED`; window conflict precedes quotation — `structural.py:246-262`
- §3.6 Allocation — revise — mismatch — remainder ranking inserts the basis row's creation sequence as the second key — `calc.py:148`
- §3.6 Allocation — insert — ambiguity — allocate/reallocate return the project resource, not the shares — `structural.py:325`
- §3.6 Reallocation — revise — mismatch — `allocation_basis` optional (basis retained); billed-share block is `ERR_INVALID_PROJECT_STATE`; window/quotation not re-checked — `structural.py:333,343`
- §3.6 Fork/join — insert — ambiguity — accept/decline return the cost share — `structural.py:506,531`
- §3.6 Decline — revise — mismatch — `decline_reason` optional, ≤500 chars — `structural.py:512`
- §3.6 Construction — insert — ambiguity — window-not-open → `ERR_INVALID_PROJECT_STATE` — `structural.py:370`
- §3.6 Certification — insert — ambiguity — share check runs after SoD, `DECLINED` blocks, code `ERR_INVALID_PROJECT_STATE` — `structural.py:387-395`
- §3.6 Cancellation — revise — mismatch — `cancellation_reason` optional ≤500; `PROPOSED`/`COST_ALLOCATED`/`STALLED` leave tower version untouched; FUNDED path also voids `PENDING`/`ACCEPTED` — `structural.py:410,431`
- §3.7 Papering — insert — ambiguity — `supersedes_amendment_id` resolved last → `ERR_AMENDMENT_NOT_FOUND` — `amendments.py:82-85`
- §3.7 Papering — insert — ambiguity — non-APPROVED or already-papered → `ERR_INVALID_APPLICATION_STATE`, before supersede validity — `amendments.py:87`
- §3.7 Execution — insert — ambiguity — `signature_received` mandatory; re-parking from `PENDING_SIGNATURE` → `ERR_INVALID_AMENDMENT_STATE` — `amendments.py:166,173`
- §3.7 Preconditions — insert — ambiguity — earliest-created `ACTIVE` ground lease is the one consulted — `services.py:20`
- §3.7 Execution effects — insert — ambiguity — superseded amendment's `terminated_at` stays null — `amendments.py:223-227`
- §3.7 Billing axis — revise — mismatch — `ERR_INVALID_BILLING_STATE` for undeclared moves first, then `ERR_INVALID_AMENDMENT_STATE` for the execution-status precondition — `amendments.py:253-262`
- §3.8 Notice — insert — ambiguity — `ERR_INVALID_AMENDMENT_STATE` then `ERR_INVALID_BILLING_STATE` — `amendments.py:276-281`
- §3.8 Decommission — insert — ambiguity — `restoration_confirmed` mandatory, `false` → `ERR_INVALID_REQUEST`; state/restoration failures → `ERR_INVALID_AMENDMENT_STATE` — `amendments.py:293-302`
- §3.9 Findings — insert — ambiguity — `site_amendment_id` existence-checked only — `amendments.py:381`
- §3.9 Finalization — insert — ambiguity — one aggregate balance movement per tenant, ordered by first billed finding — `amendments.py:453-462`
- §4 Endpoint preamble — insert — ambiguity — unknown route/method → `ERR_INVALID_REQUEST` at 404/405 — `app.py:32-36`
