# Worklog — task_2442_family_child_care_network_shared_services

## Step 1: Create task directory — 2026-09-02T17:14:30.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2442_family_child_care_network_shared_services` and its `workspace/` subdirectory. Index 2442 was pre-assigned by the orchestrating pipeline (no scan of ./tasks/ performed, per instructions, to avoid collisions with the up-to-32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-02T18:43:00.000Z

All three artifacts are complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2442_family_child_care_network_shared_services/`)
- `SCAFFOLD.yaml` (2640 lines) — §1.0–§1.7 only, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1530 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (2968 lines) — single key `scaffold_corner_design`

**Lint verdict (verbatim, final run from repo root)**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2442_family_child_care_network_shared_services/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2442_family_child_care_network_shared_services/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2442_family_child_care_network_shared_services/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    64
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  653

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Scaffold surface** — `domain_name: family-child-care-network`, `api_prefix: /fccn`, `difficulty_level: expert_plus`, archetypes ledger_reconciliation / quota_allocation, topology hybrid, state-machine shape cyclic, role model segregation_of_duties, consistency immediate. 12 entities (Provider, MembershipAgreement, Enrollment, SubsidyContract, SubsidyClaim, Remittance, FoodProgramClaim, Substitute, SubstituteAssignment, CoachingVisit, ComplianceReview, GroupPurchaseOrder), 11 state machines, 2 OCC `concurrency_rules`, 8 calculations, 16 ordered validation priorities, 64 endpoints (40 POST / 24 GET, incl. `POST /_clock/set_current_utc`), 49 errors, 6 roles each with `identity:` (Anonymous/NetworkAdmin/FiscalOfficer/QualityCoach opaque; Provider and Substitute `entity_backed:`).

**§1.8 difficulty coverage** — 9 rule_ids × 2 instances = 18, each with an explicit differentiation clause: dual_variant_calc (claim provisional-vs-final; quality coaching-weighted-vs-compliance-anchored), combinatorial_formula (GPO per-line-round-then-sum mode B; substitute fee tier keyed on pre-fee subtotal mode C), non_linear_state_machine (agreement negotiation cycle bounded at 3 rounds; assignment parallel staffing/billing dimensions with decline re-offer loop), transitive_cascade (quality escalation depth 4; enrollment withdraw depth 3), priority_pair_validation_conflict (state 9 beats fiscal 16; safety 12 beats temporal 13), boundary_precision_check (margin at exactly 15%; food tier at exactly 50% subsidy share), cross_entity_state_dependency (remittance blocked by SUSPENDED_FOR_QUALITY contract; transfer requires eligible receiving provider), resource_temporal_overlap (half-open window + 30-min buffer at the exact gap; inclusive ±29-day coaching saturation), compensating_invariant (remittance reversal ledger conservation; claim rejection authorization conservation).

**§1.9 corner coverage** — 55 instances across all nine guide sections, no invented sections or claim_types: Entities 12, State Machines 16 (9 real + 7 stubs), Calculations 13 (5 real + 8 stubs), Validations 9 (5 + 4), Endpoints 7 (4 + 3), Errors 20 (11 + 9), RBAC 6, Cross-Cutting Complexity Layers 5 (2 OCC real + 3 stubs), Consistency Model 1. All 49 error ids are triggerable: 11 new real triggers in the Errors section, 9 `excluded_because` stubs pointing at the §1.8 instance that asserts them, and the rest exercised by other §1.9 sections (12 NOT_FOUND ids in one Entities instance, ERR_INVALID_REQUEST, RBAC's 5 ids, the 2 OCC ids).

**Verification beyond the lint** (scripted, all zero-violation): every `grounds:` entry in both files resolves to a declared §1.1–§1.7 element; 107 instance names unique across the union; every `${var}` in paths/payloads/`as_user_id`/asserts bound by an earlier `captures:`; every stub cites an existing §1.8 instance name and carries no `test_recipe`.

**Design adjudications made this session**
- Errors section has no claim_type rows in the guide (it only mandates triggerability), so I used `claim_type: Triggerable` there rather than inventing category names; RBAC's non-role-model bullets became `Exclusive Operations Allowed` / `Cross-Role Denial`, with `peer_roles` and `Segregation of duties` used for the rows the guide does define.
- Entities' Immutability row was skipped without a stub — every entity is `common_fields: true`, so the row is non-applicable.
- Bulk-action rollback is demonstrated with a line that omits `quantity` (priority-7 required-field path) rather than an out-of-range quantity, since no numeric range for line quantity is declared in §1.4's ERR_INVALID_REQUEST list.
- `ERR_LICENSE_EXPIRED`, `ERR_CAP_DEADLINE_PASSED` and `ERR_VISIT_DATE_IN_PAST` are all driven through `POST /_clock/set_current_utc` (or the default clock) rather than wall-clock waits; the visit instance also asserts the strictly-before boundary by accepting `scheduled_on` equal to the clock date.
- `ERR_REMITTANCE_NOT_FOUND` and `ERR_INVALID_REMITTANCE_STATE` are triggered through `POST /fccn/remittances/{id}/reverse` because §1.5 declares no `GET /fccn/remittances/{id}`.
- The chronological-waterfall corner deliberately creates the 2026-08 claim before the 2026-07 claim so that a created_at ordering would give the wrong answer; the partial-allocation corner pins 90000 + 10000 with `unallocated_cents == 0`.
- Both OCC corners avoid arithmetic on versions: the stale value is a genuinely superseded `${var}` (bumped by the first agreement create / by the subsidy-slot commit), and each asserts the successful retry after a re-read.
- Numeric literals were re-derived in Python this session for the GPO order (total_quantity 16, discount 0.05, lines 4750/5694/9500, subtotal and total 19944) and for the 80%-advance floor case (provisional 4503, advance 3602, final 4503, delta 901, chosen specifically because round-half-up would give 3603/900).

## Step 3: Copy shared files — 2026-09-02T18:43:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T18:55:00.000Z

The PRD is complete and verified. `/tmp` scratch files (`gen_tail_2442.py`, `verify_2442.py`, three JSON requirement sets) were used only as verification tooling; nothing was written into the task directory except `workspace/PRD.md`.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2442_family_child_care_network_shared_services/workspace/PRD.md` (378 lines, ~90 KB)

**Structure**

- **§1 Introduction** — 3 paragraphs, framed on the provider's administrative burden, then the ledger-reconciliation reality (provisional advance vs. final reconciliation over the same attendance data), then the quality<->money coupling and the logical clock.
- **§2 Global Specifications** — 11 subsections, domain-derived: 2.1 Actors, Identity Headers and RBAC (all 6 roles named, all 6 `identity:` fields translated — 4 opaque, 2 entity-backed); 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, verified programmatically); 2.3 Pagination and List Ordering; 2.4 Common Resource Properties; 2.5 The Logical Clock; 2.6 Network Posture Gate; 2.7 OCC on Agreement and Claim Creation; 2.8 Rejection Precedence (all 16 priorities as an ordered ladder with every `error_id`, HTTP status and `applies_to` endpoint set); 2.9 Nested Reads and Path Resolution; 2.10 Money, Percentages and Rounding Discipline; 2.11 Cascades, Compensation and Conserved Quantities (3 conservation invariants, immediate consistency).
- **§3 Business Logic** — 9 subsections grouped by shared-service line: 3.1 recruitment/licensing/agreement negotiation cycle; 3.2 enrollment, capacity, slot conservation, transfers; 3.3 subsidy contract + claim ledger (both `subsidy_claim_amount` variants); 3.4 remittance waterfall + reversal; 3.5 food program tiering; 3.6 substitute pool selector + cost ladder; 3.7 coaching, both `provider_quality_score` variants, CAP cycle, 4-hop escalation + 4-hop compensating reinstatement; 3.8 group purchasing + full revenue-projection model; 3.9 network exit and family transition.
- **§4** 4-column table, 64 rows. **§5** 2-column table, 49 rows.

**Completeness verification (scripted against SCAFFOLD.yaml)**

```
Field coverage check:
- entities[].fields: 108 required, 108 present, 0 missing
- endpoints[].input/request_body + query/path params + nested object keys
  + revenue-model output keys: 141 total required set, 141 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 16 checked, 16 expressed in prose (§2.8 explicit ordered ladder), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_provider_version /
  expected_contract_version + ERR_STALE_PROVIDER_VERSION / ERR_STALE_CONTRACT_VERSION + 412), 0 missing
- state_machines[].transitions: 11 machines / 51 transitions checked, 51 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed (all constants embedded in business context;
  pinned rounding/evaluation orders called out), 0 missing
- validations[] conditions: 16 checked, all matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 64 endpoints checked, all side-effect lists expressed, 0 missing
- entities[].fields[] structured content: 108 checked (types, defaults, initial values, enum sets), 0 missing
- sibling-branch symmetry: 9 groups checked (food approve +/- disallowance, claim HELD from DRAFT vs SUBMITTED,
  HELD->DRAFT vs HELD->SUBMITTED, agreement withdraw from SENT vs COUNTERED, enrollment withdraw from
  ENROLLED vs TRANSITION_PENDING, contract ->TERMINATED from ACTIVE vs SUSPENDED_FOR_QUALITY,
  provider ->EXITING from ACTIVE vs PROBATION, submit-cap from OPEN vs CAP_REJECTED,
  assignment ->OFFERED vs ->UNFILLED), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 738
- tokens starting with `/`: 0   bare HTTP-method tokens: 0   method+path tokens: 0
- raw "/fccn" occurrences anywhere in §3: 0
Status: PASS

Additional mechanical checks:
- all 63 distinct endpoint paths (64 endpoint rows) present in PRD: PASS
- all 49 error ids present in §5 table AND each also mentioned in §2/§3 narrative: PASS
- all state values across 11 machines present verbatim: PASS
- all enum-type field values present verbatim: PASS
- all 6 role names present verbatim: PASS
- §2.2 identical to section-2.2-response-structure.md: PASS
- no fuzzy/approximating words ("approximately", "roughly", "conservatively", ...): PASS
- file ends at a real section boundary (final row of the §5 error table): PASS
```

**Two scaffold internal inconsistencies resolved (worth flagging to the scaffold owner):** (1) `MembershipAgreement.round_index` — §1.1 says default 1 on creation, but the create endpoint's `side_effects` say `round_index := 0`; I followed §1.1 (created at 1, counter permitted only while below 3). (2) auto-opened compliance review `cap_due_on` — the state machine says clock date + 14 days, the `conduct` endpoint says request value defaulting to clock date + 30 days; I followed the endpoint entry, since it is the more specific one and is the only place the `cap_due_on` / `critical_standard_codes` request fields exist.

**Orchestrator truncation check (independent of subagent):** `tail -c 1200 workspace/PRD.md` ends with the final `ERR_CONTRACT_AUTHORIZATION_EXCEEDED | 402` row of the §5 table — a real section boundary, no mid-sentence cut. Section header scan shows §1 through §5 all present with §3.1–§3.9 intact. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-02T20:13:00.000Z

Test suite generation is complete. Final state and audits:

## Files written

**Stage 1 — `test_helpers/`** (9 modules): `types.py`, `api_errors.py` (48 codes + HTTP status map registered at import), `constants.py`, `test_users.py` (6 role identities incl. `NO_AUTH_HEADERS`), `api_client.py` (66 methods, prefix `/fccn`), `factories.py`, `fixtures.py` (state builders reaching every interesting state through published endpoints only), `assertions.py`, `__init__.py`.

**Stage 2 — `test_suite/`** (conftest + 12 test modules, 89 tests):

| file | tests | queue |
|---|---|---|
| `test_01_dual_variant_and_combinatorial.py` | 8 | A |
| `test_02_state_machine_and_cascade.py` | 8 | A |
| `test_03_priority_and_boundary.py` | 8 | A |
| `test_04_cross_entity_and_temporal.py` | 8 | A |
| `test_05_compensating_invariant.py` | 4 | A |
| `test_10_corner_entities.py` | 10 | B |
| `test_11_corner_state_machines.py` | 9 | B |
| `test_12_corner_calculations.py` | 5 | B |
| `test_13_corner_validations.py` | 5 | B |
| `test_14_corner_endpoints_and_layers.py` | 7 | B |
| `test_15_corner_errors.py` | 11 | B |
| `test_16_corner_rbac.py` | 6 | B |

**Queue A: 36 tests. Queue B: 53 tests. Total 89.**

## Audit results

- **PRD-citation pass:** 100 `PRD: "…"` citations extracted and whitespace-normalised against `workspace/PRD.md` — **0 missing**, all verbatim and grep-survivable.
- **Design-tag / coverage pass:** 89 tests, each with **exactly one** `Design:` line; 0 tags pointing at a stub or non-existent instance. Queue A: 18 live instances (0 stubs), every one covered by exactly 2 tests. Queue B: 55 live instances (34 stubs, none translated), 53 covered >=1; the 2 uncovered are the documented skips.
- `python -m pyflakes test_suite/*.py test_helpers/*.py` -> clean. `pytest test_suite --collect-only -q` -> 89 collected, no import errors.
- No occurrence of "scaffold", the section sign, `skip`, `xfail`, `TODO` in generated code.
- Fixed a latent defect in already-written files: `validate_success()` returns `body["data"]` (the array for list endpoints), so 9 `validate_success(...)["meta"]["total_count"]` reads in test_03/test_04/test_13 were invalid; all rewritten as `_, meta = validate_paginated(...)`.

## Skipped instances (2, both queue B / Entities)

1. `provider_apply_missing_required_capacity_slots_is_rejected` — PRD §3.1 makes `capacity_slots` optional ("must fall between 1 and 12 **whenever a value is present**"), so `ERR_INVALID_REQUEST` for omitting it is not uniquely derived.
2. `enrollment_create_with_unknown_provider_id_returns_provider_not_found` — unreachable: role `Provider` with a nonexistent `X-User-ID` fails rung 2 (401) and a real provider fails rung 4 (403), so rung 6 can never be reached on this endpoint.

## Divergences from the design yamls (PRD wins in every case)

1. `provider_apply_with_all_required_fields…` — PRD §3.1 nulls all three licensing fields at apply; asserts `license_number`/`license_expires_on`/`capacity_slots` are None (yaml expected `capacity_slots == 6`).
2. `provider_get_by_id_returns_the_stored_entity_unchanged` — same reason; both licensing fields asserted None.
3. `provider_apply_capacity_slots_outside_one_to_twelve_is_rejected` — stored capacity is null, so only 201 + `total_count == 1` asserted.
4. `provider_system_fields_are_server_generated…` — dropped the `updated_at == 2026-08-01T00:00:00Z` assertion (§2.2 mandates three fractional digits).
5. `enrollment_create_makes_every_derived_field_visible…` — yaml says `rev1 == 60000`; PRD §3.9 gives 1 × 4500 × 22 + 60000 = **159000**.
6. `commit_an_already_committed_order…` — yaml prose says "subtotal stays 4750" but its asserts say 5000 (total_quantity 5 => no discount); followed the asserts.
7. `anonymous_cannot_create_an_enrollment…` — `Anonymous` is one of the six declared roles, so `X-User-Role: Anonymous` would be 403; interpreted `as: Anonymous` as *no identity headers*, which makes rung 1 uniquely derive 401.
8. Scaffold self-contradiction `round_index := 0` vs entity default 1 — PRD gives 1.
9. `severity: SERIOUS` / `severity: MODERATE` are not PRD enum members (MINOR/MAJOR/CRITICAL) — used `MAJOR`.
10. Meal-line field names corrected to `service_date`/`breakfasts`/`lunches`/`snacks`; `findings` emitted as an array of codes.
11. `enrollment_create_after_the_license_lapses…` — yaml expects `network_posture == NORMAL`; PRD §2.6 maps `ACTIVE -> OPEN`, so `OPEN` is asserted.

Nothing under `workspace/implementation/` was read or written. The suite was not executed (no server run) — that is Step 7's sweep.

## Step 6: Generate implementation — 2026-09-02T19:45:00.000Z

Implementation complete and verified.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2442_family_child_care_network_shared_services/workspace/implementation/` — 18 files:

**Launcher / deps:** `start.sh` (executable; `set -euo pipefail`, `cd $(dirname $0)`, guarded flask install, `exec python3 app.py`), `requirements.txt`.

**Core modules:** `app.py` (app factory, 9 blueprints, global `RLock` per request, ApiError/404/405/HTTPException/Exception handlers, `0.0.0.0:$PORT`), `db.py` (12 in-memory dicts, `make_row`, internal `_seq` for `created_at` ASC), `errors.py` (49 PRD codes + 3 harness fallbacks), `response.py` (meta/envelope, `_`-prefix stripping), `clock.py` (logical clock, default `2026-08-01T00:00:00Z`), `auth.py` (6 roles, ladder steps 1–4), `validators.py` (shape checks, `reject_unversioned`, pagination), `calculations.py` (7 calculations + selector), `services.py` (version-touch dedupe, posture, cascades, slot ledger).

**Routes package:** `routes/` with `__init__.py` + `providers.py`, `agreements.py`, `enrollments.py`, `subsidy.py`, `food.py`, `substitutes.py`, `quality.py`, `orders.py`, `clock_api.py`.

## Endpoint count

**64 registered routes: 40 POST + 24 GET.** Diffed the GET set against the PRD table line-by-line — exact match, no extras, no gaps. All 49 error codes match the PRD's HTTP statuses exactly (verified programmatically).

## Verification performed

One bug found and fixed: `calculations._overlaps` used `timedelta` without importing it — a latent `NameError` on the first buffered-interval conflict evaluation. Added `from datetime import timedelta`.

Ran ~110 live assertions across 5 smoke scripts on fresh servers, all passing. Coverage: full onboarding chain; OCC 412 on both declared points and `ERR_INVALID_REQUEST` for the two version fields anywhere else; the negotiation cycle to `round_index` 3 plus `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`; slot/capacity/duplicate-child gates; provisional (joint 22-day cap) vs. final (independent caps, absence allowance, zero absence for withdrawn children) valuations; the `//` truncating advance; `ERR_CONTRACT_AUTHORIZATION_EXCEEDED` at 402; the multi-claim remittance waterfall ordered by `period_month`/`created_at` with partial allocation, surplus credit, reversal and the §2.11 conservation identity holding at zero drift; food tiering at both TIER_I and TIER_II with per-(child, date) caps and disallowance; substitute selection (credential rank, county tier, declined list, 30-minute buffered conflict at both 12:20 reject / 12:31 accept), 4-hour minimum, 18% premium, fee tiers; coaching weighted score with 3 visits, compliance-anchored variant, segregation of duties on both conduct and close; the 4-hop escalation cascade and its exact inverse (including `claimed_amount_cents` restored with zero drift and held enrollments dropping out of / returning to projected revenue); exit cascade, `ERR_EXIT_TRANSITIONS_PENDING`, contract termination; transfer with `predecessor_enrollment_id` chain and slot hand-off; group purchase discount ladder and 3% insurance fee; revenue model in all three sustainability bands plus `INSUFFICIENT_DATA` and the ROUND_CEILING 500-cent tuition guidance; pagination bounds, filters, ordering; and ladder precedence spot-checks (body-FK 404 before shape 400, posture 409 masking licensure 422, own-entity state 409 masking aggregate 409).

Also confirmed the harness contract: three simultaneous boots each started with zero rows and stayed isolated; no `.db`/`.sqlite`/`.json`/`/tmp` artifact is ever written (only `__pycache__`, which I removed).

## PRD ambiguities resolved

Carried over from the earlier session (23 items, unchanged) plus resolved this session:

- **Provider `version` on agreement issuance** — bumped unconditionally, since the OCC race narrative in §2.7 requires a stale reader to be detected even when nothing was actually superseded.
- **Scope vs. existence ordering** — scope check first when the path parameter *is* the provider id (ladder step 4 precedes 5); 404-then-403 when ownership is only reachable through a parent chain, since the parent must be read to learn the owner.
- **Claim drafting against a TERMINATED contract** — `ERR_CONTRACT_NOT_ACTIVE`; `advance` requires an ACTIVE contract while `reconcile` does not (the PRD names ACTIVE for submit and advance but is silent for reconcile).
- **Meal counts** — optional, defaulting to 0; caps aggregated per (`child_ref`, `service_date`) across all lines rather than per line.
- **`visit_conducted_on` out of bounds** — treated as a shape failure (`ERR_INVALID_REQUEST` at step 7), so it masks `ERR_SEGREGATION_OF_DUTIES` at step 12.
- **`quality_variant_applied`** — written even when the provider has no completed visits.
- **Escalate check order** — review state (step 9) -> provider ACTIVE (step 9, same tier) -> `cap_rejection_count` (step 15).
- **Provider-role enrollment listing** — scoped to the acting provider.
- **Duplicate `agency_reference` among POSTED remittances** — no dedicated code exists in the PRD table, so it returns `ERR_INVALID_REQUEST` 400, consistent with the explicitly-specified duplicate-food-month case; the reference becomes reusable after reversal.
- **Unknown body fields** — only the two declared names (`expected_provider_version`, `expected_contract_version`) are rejected outside their endpoints, per §2.7's exact wording; arbitrary unrecognized keys are ignored, as no PRD sentence forbids them.
- **`offset` beyond `total_count`** — returns an empty page, not 400; §2.4 bounds only `limit` (1–100) and forbids negative `offset`.

*(Orchestrator note: Steps 5 and 6 were launched concurrently in a single assistant message, so the impl-gen subagent could not see `test_suite/`; it finished first at ~20:35Z while the test generator continued to ~21:00Z. Entries are recorded in step order, not completion order.)*

## Step 7: Run tests and iterate — 2026-09-02T20:36:00.000Z

All 8 rounds are green (89/89 each), verified by reading the results files just now.

## Summary

**Iterations run:** 2 (each an 8-round parallel sweep under `setsid nohup`).

- Iteration 1: 79/89 in all 8 rounds — identical failure set every round (no flakiness, no load artifacts).
- Iteration 2: 89/89 in all 8 rounds (`results.1..8.json` on disk, all complete JSON with `passed == total == 89`).

**Tests deleted:** none. Every failing test's rule traced verbatim to PRD.md and was uniquely derivable, so all 10 failures were genuine test-artifact or implementation defects.

**Fixes applied to `test_suite/` (test bugs — STEP 2, setup inconsistent with PRD):**
- `test_11_corner_state_machines.py`, `test_12_corner_calculations.py`, `test_15_corner_errors.py`, `test_16_corner_rbac.py` — setup fixtures issued membership agreements with `shared_services: ["COACHING"]` (and one 4-element list containing `"COACHING"`). PRD §3.1 declares the set exactly as `ENROLLMENT`, `BILLING`, `FOOD_PROGRAM`, `SUBSTITUTE_POOL`, `GROUP_PURCHASING`, so the PRD-faithful implementation correctly answered `ERR_INVALID_REQUEST` and 7 tests died in setup. Replaced with valid members (`["ENROLLMENT"]`; `FOOD_PROGRAM` in the 4-element list). `shared_services` content gates nothing in PRD, so the assertions under test are unaffected.
- `test_11_corner_state_machines.py::test_executing_an_already_executed_agreement_is_refused_and_fires_no_side_effect` — asserted provider `version == 3` after apply -> verify -> issue -> execute, and its docstring enumerated only three bumps. PRD §3.1 states the issue bumps the provider unconditionally ("Issuing it is also a supersede: ... and the provider's own `version` is incremented by one"), which §2.7's rationale requires (otherwise a second issue on a stale version would silently retire the unseen first agreement — the exact harm the check exists to prevent) and which the passing `test_14::test_re_using_the_provider_version_the_first_agreement_consumed_is_refused` depends on. Corrected the expectation to 4 in both places plus the docstring; the mis-counted assertion, not the implementation, was wrong.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/providers.py`, `apply_to_network` — was persisting the applicant's volunteered `license_number` / `license_expires_on` / `capacity_slots`. PRD §3.1: "All three of those licensing fields are null until the network verifies the license." Now the three values are still shape-validated (`capacity_slots` between 1 and 12 when present, per ladder step 7) and then discarded, with the row created carrying `None` for each. The verification endpoint continues to write the authoritative values.

**Fixes applied to `test_helpers/`:** none needed — the shared fixtures were PRD-faithful; the invalid enum values were inline in the test files' local setup builders.

*(Orchestrator verification, run independently of the subagent's claim: all 8 `workspace/implementation/results.*.json` exist as complete JSON, each `passed == total == 89`, `failed == 0`, all mtime 20:24:56Z. Critically, that sweep POSTDATES the last artifact edit — `test_suite/test_16_corner_rbac.py` at 20:21:28Z and `workspace/implementation/routes/providers.py` at 20:22:01Z — so the green result covers the final code, not a pre-fix snapshot. `sweep.log` tail confirms 8 independent runner completions at 170.0s each with "89/89 passed, 0 failed, 0 errors, 0 skipped". Also note: the Step 1–6 timestamps I originally wrote in this worklog were estimates that ran ahead of the real host clock; Steps 5 and 6 have been corrected to match artifact mtimes, and every entry from Step 7 onward uses `date -u` readings.)*

Step 8 will run (Step 7 was not a zero-fix exit: 1 `implementation/` fix and 5 `test_suite/` fixes).

## Step 8: Finalize PRD — 2026-09-02T20:43:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_2442_family_child_care_network_shared_services/workspace/PRD_FINALIZED.md`.

## Size delta
- PRD.md: 378 lines / 89,972 bytes; PRD_FINALIZED.md: 378 lines / 90,564 bytes.
- Line count delta: 0 lines (0.00%) — both edits are in-paragraph inserts. Byte delta +592 (+0.66%).

## Changes (2 total)
- **§3.1 (membership agreement issue) — insert** — pinned that the provider's `version` bump on `POST /fccn/membership-agreements` is unconditional (exactly +1 on every successful issue, even when no `SENT`/`COUNTERED` agreement existed to supersede). The original sentence's trailing clause could be read as conditional on a supersede actually happening, which is exactly the reading the Step 7 test bug encoded (`version == 3` vs `4`). — `implementation/routes/agreements.py:69`
- **§3.1 (license verification) — insert** — pinned the `capacity_slots` fallback and its failure mode: an omitted `capacity_slots` falls back to the capacity stored on the provider; the effective figure must be an integer 1–12 checked at request-shape priority; and because an applicant's own `capacity_slots` is null (the direct consequence of the Step 7 fix that discards volunteered licensing fields), a verification that omits the field always fails with `ERR_INVALID_REQUEST`. — `implementation/routes/providers.py:71-74` (with `:38`/`:46` as the reason the fallback is always null)

## Step 7 items deliberately NOT patched
- **`shared_services: ["COACHING"]` fixture bug (4 test files)** — pure test-setup bug. PRD §3.1 already declares the set exactly, and §2.8 band 7 already makes an out-of-set enum `ERR_INVALID_REQUEST`. Grep confirms `shared_services` is write-only in the impl (`routes/agreements.py:36,50`, read nowhere), so PRD's silence about it gating anything matches the impl. No edit.
- **`apply_to_network` discarding volunteered licensing fields** — the impl was fixed *to* the PRD; PRD §3.1 already says "All three of those licensing fields are null until the network verifies the license" and already pins the 1–12 shape check "whenever a value is present". Prose kept verbatim; only the downstream verification consequence (edit 2) needed pinning.

## Per-edit pre-edit search log

**Edit 1 — provider `version` bump on agreement issue**
- (a) Subject: when and how much the provider row's `version` moves during `POST /fccn/membership-agreements`, plus every other provider-version-mutating path (so the new "unconditional / exactly one" wording can't over-claim).
- (b) Paths enumerated (read/grepped): `routes/agreements.py:27-72` (`issue_agreement`: stale check at 40-44 raises *before* any mutation; supersede loop 61-68 touches only sibling agreements; `services.touch(provider)` at 69 is outside the loop and unguarded); `services.touch` / `register_new` semantics (`services.py:23-44` — at most one bump per row per request, new rows pinned at version 1, so the issue cannot double-bump); grep for all other provider-version writers — `services.set_membership_status` (`services.py:94-98`, called from `routes/providers.py:90,128,150` and `routes/agreements.py:140`), `recompute_revenue` (`services.py:137-142`; callers in `routes/enrollments.py:83,105,168,169`, `routes/food.py:140`, `routes/substitutes.py:221`, cascades `services.py:219,246,261`), `rescore_quality` (`services.py:145-159`; `routes/quality.py:151,241`), `recompute_open_finding_count` (`services.py:125-134`, which bumps *only* when the count actually changes; `routes/quality.py:51,200,217,240,268`).
- (c) Adjustment: scoped the new sentence explicitly to "every successful issue" rather than any general statement about provider version bumps. This was necessary because `recompute_open_finding_count` is conditional (no bump when the count is unchanged) and `touch` is idempotent per request — a broader "the provider's version always bumps by one whenever X" phrasing would have mis-described those paths. Also said "successful issue" so the `ERR_STALE_PROVIDER_VERSION` path (no bump) stays correctly described.

**Edit 2 — `capacity_slots` at license verification**
- (a) Subject: every read and write of `Provider.capacity_slots`, and the error a missing/invalid effective capacity produces.
- (b) Paths enumerated (read/grepped `capacity_slots` across `implementation/`): `routes/providers.py:38` (apply shape-checks 1–12 then discards), `:46` (row created with `None`), `:71` (`opt_int(..., None, 1, 12)`), `:72-74` (fallback to the stored value, then `v.bad` -> `ERR_INVALID_REQUEST`), `:76-80` (APPLICANT state check, which runs *after* the shape check — consistent with §2.8 bands 7 < 9), `:81-85` (expiry check, band 12), `:89` (the only other writer); readers `routes/enrollments.py:53` (`provider["capacity_slots"] or 0` for `ERR_CAPACITY_EXCEEDED`) and `:135` (same for the receiving provider in a transfer).
- (c) Adjustment: I did **not** write "`capacity_slots` is required on this endpoint." That would be a new mismatch: for a provider that already carries a stored capacity (any non-`APPLICANT` provider), omitting the field passes the shape check and the request instead fails later with `ERR_INVALID_PROVIDER_STATE`. Final wording keeps the fallback rule as the general statement and derives the always-fails result specifically from the applicant's capacity being null, and says "checked at request-shape priority" instead of naming a fixed position relative to the state/expiry checks, so §2.8's existing ladder remains the single source of ordering. The `or 0` readers in `enrollments.py` are untouched by this wording since both are reachable only for `ACTIVE` providers whose capacity is non-null.

## Step 9: Complete PRD — 2026-09-02T21:12:00.000Z

All planned edits are applied and verified. Final report:

## Verification

- `PRD_FINALIZED.md`: 378 lines / 90,564 chars -> `PRD_COMPLETED.md`: 378 lines / 105,114 chars (**char delta +14,550**; line count unchanged because every edit was an in-paragraph insert or revision — no new paragraphs, no new sections).
- §5 table still holds exactly 49 `ERR_*` rows (same as source) and the file's last line is `| `ERR_CONTRACT_AUTHORIZATION_EXCEEDED` | 402 |` — a real section boundary, not truncated.
- Only `workspace/PRD_COMPLETED.md` was modified.

## Counts

**98 pins across 46 changed lines: 85 ambiguity-pins, 13 mismatch-revisions.**

Mismatch-revisions (PRD asserted something impl does not do): §2.4 version rule x1, §2.6 posture-gate x3, §2.8 ladder x3, §3.1 execute order x1, §3.3 draft contract status x1, §3.6 accept order x1, §3.7 conduct/escalate order x2, §3.8 tuition rounding x1.

## Changes

**§2.1** — insert — ambiguity — anonymous apply: absent/empty role reads as `Anonymous`, no user id needed, any other non-empty role is `ERR_FORBIDDEN_ROLE` not 401 — `auth.py:43`

**§2.2** — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `response.py:12`
**§2.2** — revise — ambiguity — `meta.timestamp` comes from the host clock, not the logical clock — `response.py:12`, `db.py:35`

**§2.3** — revise — ambiguity — non-integer `limit`/`offset` also `ERR_INVALID_REQUEST` — `validators.py:200`
**§2.3** — revise — ambiguity — `offset` unbounded above; past-the-end offset yields an empty page with `has_more` false — `validators.py:216`, `response.py:35`
**§2.3** — revise — ambiguity — same-millisecond rows keep creation sequence, so ordering is total — `db.py:53`
**§2.3** — revise — ambiguity — single-resource `meta` carries none of the four pagination fields — `response.py:26`
**§2.3** — insert — ambiguity — filters are exact string equality against the stored field — `validators.py:227`
**§2.3** — insert — ambiguity — empty-string filter counts as absent, unknown query params ignored, plus the exact recognised filter set per list endpoint — `validators.py:227` + route decls

**§2.4** — revise — ambiguity — id timestamps minted from host clock, not the logical clock — `db.py:35`
**§2.4** — insert — **mismatch** — `version` bumps at most once per request per row, and request-created rows stay at 1 — `services.py:29,36`
**§2.4** — insert — ambiguity — underscore-prefixed internal bookkeeping is never serialised — `response.py:19`

**§2.5** — revise — ambiguity — `set_current_utc` answers 200 with `data.current_utc` echoing the supplied string — `routes/clock_api.py:12`
**§2.5** — insert — ambiguity — the clock may be moved backwards — `clock.py:34`
**§2.5** — insert — ambiguity — one parser for every temporal field: ISO instant or bare `YYYY-MM-DD`, naive read as UTC, else `ERR_INVALID_REQUEST` — `clock.py:13`
**§2.5** — insert — ambiguity — supplied values stored verbatim; `executed_at`/`cap_submitted_at` carry the raw clock string; pre-set default is `2026-08-01T00:00:00Z` — `clock.py:10,44`

**§2.6** — revise — **mismatch** — gate also applies to subsidy-claim submit and order commit — `routes/subsidy.py:151`, `routes/orders.py:60`
**§2.6** — revise — **mismatch** — `RESTRICTED`-blocked set is food-claim create, coverage request and claim submit (not "the latter two") — `services.py:101`
**§2.6** — revise — **mismatch** — commit demands posture exactly `OPEN`, so `RESTRICTED` blocks it too — `routes/orders.py:60`

**§2.7** — revise — ambiguity — `version`/`expected_version` must be non-negative integers (shape check before comparison), and naming either on any other endpoint is `ERR_INVALID_REQUEST` — `validators.py:191`

**§2.8 step 4** — insert — **mismatch** — step 4 precedes step 5 only when the scoped value is an actor identifier; row-derived ownership resolves the row (and its 404) first — `routes/providers.py:18`, `routes/agreements.py:19`, `routes/substitutes.py:21`
**§2.8 step 10** — revise — **mismatch** — contract band also covers advance, and draft requires `ACTIVE` **or** `SUSPENDED_FOR_QUALITY`; reconcile/reject/reverse constrain nothing — `routes/subsidy.py:31,78,184`
**§2.8 step 11** — revise — **mismatch** — posture-gate endpoint list corrected to include claim submit and order commit — `routes/subsidy.py:151`, `routes/orders.py:60`
**§2.8 step 13** — insert — ambiguity — intra-band order: visit past-date before window saturation; clearance before buffered conflict — `routes/quality.py:57`, `routes/substitutes.py:88`

**§2.9** — insert — ambiguity — `GET /fccn/enrollments` implicitly narrows to a Provider's own rows; a foreign explicit `provider_id` is `ERR_PROVIDER_SCOPE_VIOLATION` — `routes/enrollments.py:173`
**§2.9** — insert — ambiguity — substitute-nested list matches current `substitute_id`, so declined windows drop out — `routes/substitutes.py:247`

**§2.10** — insert — ambiguity — one-decimal presentation of `network_fee_pct`/`observation_score` is convention only; range is validated, value stored as supplied — `validators.py:71`

**§2.11** — insert — ambiguity — revenue recompute always touches the provider; finding-count recompute touches only on an actual change — `services.py:125,137`

**§3.1** — revise — ambiguity — volunteered licensing fields are shape-checked then discarded, so bad volunteered values still fail — `routes/providers.py:34`
**§3.1** — insert — ambiguity — `license_number` required non-empty on verification — `routes/providers.py:69`
**§3.1** — insert — ambiguity — `license_expires_on` required and parseable — `routes/providers.py:70`
**§3.1** — revise — ambiguity — non-`APPLICANT` status is `ERR_INVALID_PROVIDER_STATE` — `routes/providers.py:76`
**§3.1** — insert — ambiguity — expiry `<=` clock is `ERR_LICENSE_EXPIRED`, checked after the state check — `routes/providers.py:81`
**§3.1** — revise — ambiguity — verification returns the updated provider row — `routes/providers.py:91`
**§3.1** — revise — ambiguity — counter's `accept`-side fee required and in 0–15 — `routes/agreements.py:75`
**§3.1** — revise — ambiguity — revise's `network_fee_pct` required and in 0–15 — `routes/agreements.py:98`
**§3.1** — revise — ambiguity — a revision does not touch `round_index` — `routes/agreements.py:98`
**§3.1** — insert — ambiguity — `withdrawal_reason` required non-empty — `routes/agreements.py:144`
**§3.1** — revise — ambiguity — withdrawal leaves `superseded` false — `routes/agreements.py:144`
**§3.1** — insert — ambiguity — revise and withdraw are not ownership-scoped (NetworkAdmin only) — `routes/agreements.py:98,144`
**§3.1** — revise — **mismatch** — execute checks `SENT` status first, then provider `PENDING_AGREEMENT` — `routes/agreements.py:118`
**§3.1** — revise — ambiguity — non-`PENDING_AGREEMENT` provider is `ERR_INVALID_PROVIDER_STATE` — `routes/agreements.py:118`
**§3.1** — revise — ambiguity — licence expiry equal to the clock, or absent, also fails the currency check — `services.py:116`
**§3.1** — revise — ambiguity — execute returns the agreement, not the provider — `routes/agreements.py:118`

**§3.2** — revise — ambiguity — commitment records which contract the slot came from so a later release cannot be misdirected — `services.py:173`
**§3.2** — insert — ambiguity — no `ACTIVE` contract at all also yields the slots-exhausted refusal — `routes/enrollments.py:22`, `services.py:164`
**§3.2** — insert — ambiguity — the contract chosen is the earliest-created `ACTIVE` one — `services.py:164`
**§3.2** — insert — ambiguity — withdrawal date required and parseable — `routes/enrollments.py:87`
**§3.2** — revise — ambiguity — any other source status is `ERR_INVALID_ENROLLMENT_STATE` — `routes/enrollments.py:87`
**§3.2** — revise — ambiguity — release credits the very contract the slot was taken from, never the current earliest `ACTIVE` — `services.py:181`
**§3.2** — insert — ambiguity — `slot_committed` is read at release time — `services.py:181`
**§3.2** — revise — ambiguity — the four receiving-provider clauses are evaluated in the written order and all collapse onto `ERR_RECEIVING_PROVIDER_INELIGIBLE` — `routes/enrollments.py:109`
**§3.2** — revise — ambiguity — source `TRANSITION_PENDING` is checked before all four — `routes/enrollments.py:109`

**§3.3** — revise — ambiguity — all three line keys required, extra keys ignored not rejected — `routes/subsidy.py:78`
**§3.3** — revise — **mismatch** — draft accepts `ACTIVE` or `SUSPENDED_FOR_QUALITY`; `TERMINATED` is `ERR_CONTRACT_NOT_ACTIVE`, checked after the version compare and before the posture gate — `routes/subsidy.py:78`
**§3.3** — revise — ambiguity — lines naming the same enrollment keep their stored-array position — `calculations.py:67`
**§3.3** — revise — ambiguity — `ADVANCE_PAID` is reconciliation's only precondition; contract status and posture are not consulted — `routes/subsidy.py:198`
**§3.3** — revise — ambiguity — final-amount tie order is stored-array position — `calculations.py:67`
**§3.3** — revise — ambiguity — `rejection_reason` required non-empty — `routes/subsidy.py:215`
**§3.3** — insert — ambiguity — rejection asks nothing of the contract's status — `routes/subsidy.py:215`

**§3.4** — revise — ambiguity — duplicate `agency_reference` is `ERR_INVALID_REQUEST` at shape priority, ahead of the contract-status check — `routes/subsidy.py:236`
**§3.4** — insert — ambiguity — a reference from a `REVERSED` remittance is free again — `routes/subsidy.py:236`
**§3.4** — revise — ambiguity — `reversal_reason` required non-empty — `routes/subsidy.py:291`
**§3.4** — insert — ambiguity — reversal asks nothing of the contract's status — `routes/subsidy.py:291`

**§3.5** — insert — ambiguity — `child_ref` required non-empty, `service_date` required parseable, three counts optional defaulting to 0, and `snacks` shape admits 2 so over-count is a cap violation — `routes/food.py:28`
**§3.5** — revise — ambiguity — the period-uniqueness bar applies whatever the earlier claim's status — `routes/food.py:28`
**§3.5** — revise — ambiguity — that duplicate is raised at shape priority, ahead of the posture gate — `routes/food.py:28`
**§3.5** — revise — ambiguity — the subsidy-share denominator counts enrollments in any status, terminal included — `calculations.py:232`
**§3.5** — revise — ambiguity — meal caps are measured over the aggregate of every line sharing the `child_ref`/`service_date` pair — `routes/food.py:28`
**§3.5** — revise — ambiguity — a non-`SUBMITTED` food claim is `ERR_INVALID_CLAIM_STATE`, checked after array shape and before member matching — `routes/food.py:104`
**§3.5** — revise — ambiguity — the disallowance array must hold non-empty strings — `routes/food.py:104`

**§3.6** — revise — ambiguity — both clearance-determination fields optional; supplying neither still succeeds and only bumps `version` — `routes/substitutes.py:54`
**§3.6** — revise — ambiguity — `end_at` <= `start_at` is `ERR_INVALID_REQUEST`, raised before the posture gate — `routes/substitutes.py:88`
**§3.6** — insert — ambiguity — for a named member only clearance and buffered conflict fail loudly, in that order; any other ineligibility silently yields `UNFILLED` with no selector fallback — `routes/substitutes.py:88`, `calculations.py:298`
**§3.6** — revise — **mismatch** — accept checks ownership first (null `substitute_id` -> `ERR_SUBSTITUTE_SCOPE_VIOLATION`), then pool status, then clearance — `routes/substitutes.py:152`
**§3.6** — revise — ambiguity — decline is ownership-scoped on the same terms — `routes/substitutes.py:177`
**§3.6** — revise — ambiguity — completing an unfinished window returns `ERR_INVALID_ASSIGNMENT_STATE` — `routes/substitutes.py:196`
**§3.6** — insert — ambiguity — invoice: other billing statuses are `ERR_INVALID_ASSIGNMENT_STATE`, and no ownership scope applies — `routes/substitutes.py:225`

**§3.7** — revise — ambiguity — the scheduling checks apply in the written order — `routes/quality.py:57`
**§3.7** — revise — ambiguity — the past-date check precedes the rationing rule — `routes/quality.py:57`
**§3.7** — revise — ambiguity — all four conduct fields required, `findings` alone may be empty — `routes/quality.py:103`
**§3.7** — revise — ambiguity — `critical_standard_codes` is a non-empty-string array — `routes/quality.py:103`
**§3.7** — revise — ambiguity — those codes are ignored unless the visit is critical — `routes/quality.py:103`
**§3.7** — revise — **mismatch** — the conducted-date window failure is `ERR_INVALID_REQUEST` and masks both the `SCHEDULED` state check and the SoD check that follow — `routes/quality.py:103`
**§3.7** — revise — ambiguity — `corrective_action_due_on` required but not required to be future-dated — `routes/quality.py:178`
**§3.7** — revise — ambiguity — the defaulted due date renders as `YYYY-MM-DDT00:00:00.000Z` — `clock.py:70`
**§3.7** — insert — ambiguity — CAP rejection applies no SoD comparison and needs no body — `routes/quality.py:204`
**§3.7** — revise — **mismatch** — escalation order is review `CAP_REJECTED`, then provider `ACTIVE` (`ERR_INVALID_PROVIDER_STATE`, 409), then the rejection count — `routes/quality.py:245`
**§3.7** — revise — ambiguity — reinstatement returns `ERR_INVALID_PROVIDER_STATE` for both failures, status tested before finding count — `routes/providers.py:96`

**§3.8** — insert — ambiguity — commit checks order status first (`ERR_INVALID_ORDER_STATE`), then posture — `routes/orders.py:60`
**§3.8** — revise — ambiguity — `discount_pct` is 0 when no volume rung is reached — `calculations.py:160`
**§3.8** — insert — ambiguity — the revenue-model read returns the bare ten-field model, with none of the §2.4 housekeeping fields — `routes/providers.py:178`
**§3.8** — insert — ambiguity — enrollments present but zero revenue skips the division: `margin_pct` 0.0000, `sustainability` `AT_RISK` — `calculations.py:388`
**§3.8** — revise — **mismatch** — tuition guidance rounds up *to* a multiple of 500, leaving an exact multiple (and 0) unchanged, and is produced on any sustainability band — `calculations.py:405`

**§3.9** — revise — ambiguity — `exit_reason` required non-empty, unbounded length, checked at shape priority ahead of the membership-status check — `routes/providers.py:115`
**§3.9** — insert — ambiguity — `complete-exit` reads no body and checks no `version` — `routes/providers.py:133`
**§3.9** — insert — ambiguity — the `EXITING` check precedes the pending-transition sweep — `routes/providers.py:133`

**§5 intro** — insert — ambiguity — the three non-catalogued fallbacks `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500, in the standard envelope — `errors.py:64`, `app.py:62,66,80`
**§5 intro** — insert — ambiguity — a non-object JSON body is `ERR_INVALID_REQUEST`, while unparseable bytes are treated as an absent body — `validators.py:17`

*(Orchestrator verification: `workspace/PRD_COMPLETED.md` is 378 lines / 105,114 bytes, contains exactly 49 `| ERR_* |` table rows, and its last line is the `ERR_CONTRACT_AUTHORIZATION_EXCEEDED | 402` row — a real section boundary, no truncation. `find implementation -name '*.py' -newermt '2026-09-02 20:24:56'` returns nothing, confirming Step 8 and Step 9 were documentation-only and the verified 8x89/89 sweep still describes the shipped implementation byte-for-byte.)*

## Pipeline complete — 2026-09-02T21:13:00.000Z

All nine steps finished. Final artifact set: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 modules), `test_suite/` (conftest + 12 modules, 89 tests, 0 deleted), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/, results.1-8.json}`. Test status: 89/89 in all 8 parallel rounds.
