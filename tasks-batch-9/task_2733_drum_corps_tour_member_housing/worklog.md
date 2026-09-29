# Worklog — task_2733_drum_corps_tour_member_housing

## Step 1: Create task directory — 2026-09-04T13:14:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2733_drum_corps_tour_member_housing` and its `workspace/` subdirectory. Index 2733 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-04T14:34:00.000Z

All three scaffold artifacts are complete and lint-clean in `/home/ubuntu/github/CodingPRD/tasks/task_2733_drum_corps_tour_member_housing/`.

Linter verdict (`skills/prd-bench-scaffold-generator/scaffold_lint.py`):
```
Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     13
  §1.8 instances scanned:     20
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  823

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (absolute paths):
- `SCAFFOLD.yaml` — 3239 lines / 152 KB. No `scaffold_difficulty_design` or `scaffold_corner_design` key present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1834 lines / 125 KB. Single top-level key.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2934 lines / 213 KB. Single top-level key.

Counts:
- §1.1–§1.7: 13 entities, 61 endpoints, 12 state machines, 2 concurrency rules (OCC), 10 calculations, 57 validations (priority ladder 1–57), 68 errors, 7 roles (5 opaque staff + `Member`/`Volunteer` entity_backed).
- complexity_profile: primary `temporal_windowing`, secondary `ledger_reconciliation`, layers [optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers], flat topology, cyclic state machines, `segregation_of_duties` role model, `immediate` consistency.
- §1.8: 9 difficulty rules / 20 instances (>=2 differentiated instances per rule).
- §1.9: 9 sections / 70 instances — entities 11, state_machines 13, calculations 12, validations 11, endpoints 5, errors 6, rbac 4, cross_cutting_complexity_layers 7, consistency_model 1. Of those, 51 carry full `test_recipe`s and 19 are `excluded_because` stubs, every one citing a §1.8 instance that exists by exact name (verified programmatically; no stub carries a test_recipe, and all 90 names are unique across §1.8 ∪ §1.9).
- Error triggerability audit: all 68 catalog error ids are now referenced by at least one §1.8/§1.9 instance (five per-collection NOT_FOUND ids were initially uncovered and were folded into the `unknown_path_ids_return_not_found_per_collection` instance, which now probes eleven collections).

Constraint compliance: nothing outside the task's own directory, `skills/prd-bench-scaffold-generator/` (SKILL.md + claim-extraction-guide.md + scaffold_lint.py) was read; no sibling `task_*/` directory was listed, globbed, grepped, or opened. All large YAML was produced via chunked `cat >> … <<'EOF'` appends with a `yaml.safe_load` parse check after each chunk.

## Step 3: Copy Shared Files — 2026-09-04T14:35:00.000Z

Copied `INSTRUCTION.md` from project root into `tasks/task_2733_drum_corps_tour_member_housing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T14:53:00.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **501 lines**, 105,431 chars, ~14,600 words, built in 16 chunked `cat >>` appends. Document ends at a completed `## 5. Error Code Catalogue` (last line is the `ERR_PAYMENT_EXCEEDS_BALANCE` row), no truncation, no audit footer, no contract-report text inside the file.

**Section list**
- `# Drum Corps Tour & Member Housing API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Corps Personnel and Role-Based Access Control · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Common Resource Properties and the Logical Clock · 2.5 Identifier Resolution Order · 2.6 Validation Precedence: The Corps Priority Ladder · 2.7 Cents, Rounding and Pinned Evaluation Order · 2.8 Stale-View Protection on Roster and Housing Writes · 2.9 Cascade Discipline and Derived-Ledger Recomputation · 2.10 Segregation of Duties
- `## 3. Business Logic & Workflows` — 3.1 Opening the Season and Building the Roster · 3.2 Contracting a Member: Issue, Revision, Signature and Execution · 3.3 Financing Tuition: Installment Plans and Posted Payments · 3.4 The Billing Sweep: Late Fees, Delinquency, Promotion and Expiry · 3.5 Withdrawal and the Obligation Ladder · 3.6 Host Schools, Facility Agreements and Sleeping Arrangements · 3.7 Routing the Tour: Stops, Truck Load, Travel Time and Rehearsal Blocks · 3.8 Volunteer Screening, Shift Staffing and the Life of a Stop · 3.9 Circuit Settlement and Prize Reconciliation
- `## 4. Endpoint Definitions` — 4-column table (Method, Path, Description, Authorized Role(s))
- `## 5. Error Code Catalogue` — 2-column table (Error ID, HTTP Status Code)

**Coverage, machine-verified against SCAFFOLD.yaml (parsed with PyYAML, not grepped)**
- Endpoints: 61/61. Set-diff of `(method, path)` against `endpoints[]` — 0 missing, 0 extra, table has exactly 61 rows.
- Errors: 68/68 in scaffold order, every `http` status matches, 0 missing, 0 extra, 0 status mismatches.
- Validations: 57/57, priorities contiguous 1–57, and every `error_id` referenced by a validation appears in the document.
- Contract 1 (Field-Name Coverage): 160 required identifiers (all `entities[].fields[].name` plus every `request_body`/`input`/`query_params`/`path_params` key) — **0 missing** from backticked text.
- Contract 2 (Rule Coverage): all 12 state machines' states and every transition `from`/`to` present; both `concurrency_rules[]` OCC fields (`expected_member_version` → `ERR_STALE_MEMBER_VERSION` 412, `expected_facility_agreement_version` → `ERR_STALE_AGREEMENT_VERSION` 412) documented in §2.8; all 10 calculations narrated with pinned rounding/evaluation order, including both `member_withdrawal_obligation` variants and both `show_settlement_payout` passes. Scaffold rule constants are all present but rendered as prose numerals (e.g. `REQUIRED_CLEAR_GAP_MINUTES: 180` → "one hundred and eighty minutes", `TRUCK_LBS: 26000` → "twenty-six-thousand-pound"), so a naive digit-diff reports them absent; they were each confirmed present by reading. Fixture-style worked-example totals (e.g. 1038778, 314925, 68317) were deliberately omitted.
- Contract 3 (§3 Path Purity): 0 violations across 186 lines — no backticked token in §3 starts with `/`, is a bare HTTP method, or combines method+path; also 0 unbackticked plain-text path mentions.
- Style: 0 code fences in §3 (the document's only 4 fences are the two verbatim §2.2 JSON blocks); no fuzzy-word hits.

Constraints honored: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced, and no sibling task directory under `tasks/` was read. `worklog.md` was not modified.

Orchestrator truncation check (per pipeline guard): `wc -l` = 501 and `tail -25` shows the error catalogue table ending on a complete row — the document terminates at a real section boundary, not mid-sentence. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-04T15:40:00.000Z

Implementation complete and green.

## Files written (`workspace/implementation/`)

Foundation (1,255 lines): `store.py` 148, `errors.py` 91, `envelope.py` 84, `auth.py` 55, `validators.py` 182, `calc.py` 289, `derive.py` 227, `serialize.py` 158, `find.py` 66, `services.py` 237 — wait, that group plus `app.py` 82 and `start.sh` 10 / `requirements.txt` 1.

Routes (1,788 lines): `seasons.py` 68, `members.py` 161, `contracts.py` 159, `plans.py` 95, `payments.py` 108, `schools.py` 65, `agreements.py` 162, `housing.py` 154, `stops.py` 254, `bookings.py` 133, `volunteers.py` 112, `staffing.py` 139, `settlements.py` 152, `clock.py` 24, `__init__.py` 0.

Total 3,416 lines across 28 files. Completed this session: `routes/settlements.py`, `routes/clock.py`, `app.py`, `routes/__init__.py`.

## Verification

- **Endpoints: 61/61.** Programmatic diff of `app.url_map` against the 61 `method`+`path` pairs parsed out of `SCAFFOLD.yaml` — zero missing, zero extra.
- **RBAC: 61/61 exact.** Attached `allowed_roles` to the `auth.endpoint` wrapper and diffed each route's role set against the scaffold's `roles:` list per endpoint — zero mismatches.
- **Errors: 68/68.** Every error ID in the scaffold catalog and the PRD §5 table is present in `errors.HTTP_STATUS` with the identical HTTP status (the catalog is 68 IDs, not 70).
- **Boot contract.** `bash start.sh` runs in the foreground, guards the pip install on `import flask`, `exec`s `python3 app.py`, and binds `0.0.0.0:$PORT` (verified on 57431 and 57432 via `ss -ltnp`; both shut down by exact PID, no pattern kill).
- **Fresh-boot emptiness.** On a cold server all 12 list endpoints return `total_count: 0`, `has_more: false`, `limit: 10`, `offset: 0`, and the logical clock reads `2026-08-01T00:00:00.000Z`. No seeding anywhere — the only `seed`/`preload` hits in the tree are docstrings saying there is none, and no file/DB I/O exists.
- **Smoke test: 0 failures** across a 40-call end-to-end flow (clock set → season → member → audition OFFER → medical → contract sign/execute → OCC-checked plan → payment → reversal → school → two agreements (SPRING_TRAINING + TOUR_REHEARSAL) submit/sign → housing assign/release → stop → volunteers + screening → shifts accept/approve → rehearsal block → stop confirm → complete → settlement create/finalize → billing sweep), plus negative checks for 401 / 403 / 404 / 400 pagination / `ERR_AMOUNT_NOT_POSITIVE` / repeat-finalize 409 / unknown path / malformed JSON, all returning the correct envelope.

Calculations spot-checked live and correct: EXTENDED_6 plan → surcharge 7500, financed 307500, installment base 51250; transport plan → 1196 cuft / 7840 lbs / 1 truck; agreement 4 nights × 100 min-beds × 1200 = 480000 billable; settlement provisional 320000/820000/32800/787200 and final 940000 gross / 37600 fee / 90000 sanction (15% cap) / 10000 rebate / 822400 net / 35200 variance; season rollup housing 840000, revenue 822400, `ledger_status` RECONCILED after the sweep.

`worklog.md` was not touched, and `test_suite/` / `test_helpers/` were never read or listed.

**Orchestrator note:** Step 5 and Step 6 were launched concurrently in a single message, so the implementation generator could not see `test_suite/` (the directory did not exist at its spawn time). Step 5's first attempt died on a transient Bedrock 503 having written nothing to disk; it was resumed via SendMessage with a computed to-do list rather than respawned fresh, so the suite is generated from one continuous context and cannot diverge from itself.

## Step 5: Generate Unit Tests — 2026-09-04T16:25:00.000Z

Test generation is complete. All nine queue-B sections are now emitted, and both queues are fully covered.

## Files written

`test_helpers/` (unchanged this session)
`__init__.py` 120, `api_client.py` 271, `api_errors.py` 172, `assertions.py` 453, `constants.py` 103, `factories.py` 386, `fixtures.py` 764, `test_users.py` 118, `types.py` 431

`test_suite/` — 18 test files + `conftest.py` 61, 5,022 lines total. New this session:
- `test_error_catalogue.py` 543 (6 tests, `errors`)
- `test_access_control.py` 310 (4 tests, `rbac`)
- `test_layered_interactions.py` 294 (4 tests, `cross_cutting_complexity_layers`)
- `test_immediate_consistency.py` 89 (1 test, `consistency_model`)

Earlier files: `test_contract_medical_and_agreement_machines.py` 309/9, `test_delinquency_and_cancellation_cascades.py` 306/6, `test_fee_tier_and_heat_boundaries.py` 281/7, `test_financing_meal_and_transport_formulas.py` 267/6, `test_settlement_and_withdrawal_variants.py` 240/6, `test_validation_priority_conflicts.py` 206/4, `test_cross_entity_state_dependencies.py` 253/6, `test_housing_and_shift_overlaps.py` 207/5, `test_reversal_and_release_compensation.py` 195/5, `test_resource_representations.py` 445/11, `test_lifecycle_transitions.py` 434/10, `test_derived_calculations.py` 324/5, `test_request_validation.py` 396/6, `test_endpoint_contracts.py` 312/5.

## Test counts

- **Queue A (Difficulty / §1.8): 54 tests** across 20 rule instances — all 20 translated, >=2 tests each.
- **Queue B (Corner / §1.9): 52 tests** — entities 11, state_machines 10, calculations 5, validations 6, endpoints 5, errors 6, rbac 4, cross_cutting 4, consistency_model 1.
- **Total 106 tests.**

## Coverage audit

- 20/20 live difficulty instances translated; 51/51 live corner instances translated. **Nothing skipped for PRD-filter reasons.**
- The 19 `excluded_because:` corner stubs were correctly left untranslated (verified programmatically that no test tags one).
- Machine-verified: exactly one `Design:` line per test, always the final docstring line; every tag resolves to a real instance name; no untagged, dual-tagged or dangling tags; no `skip`/`skipif`/`xfail`; no file mentions "scaffold"; 106/106 PRD citations are byte-verbatim substrings of `workspace/PRD.md`; pyflakes clean across `test_suite/` and every module imports cleanly.

## Design deviations (all PRD-driven, recorded for Step 7)

1. Housing instances (`housing_constraint_errors_*`, `housing_stay_must_fall_inside_*`, both OCC instances, `every_derived_field_is_visible_*`) register only APPLICANT members, but PRD rung 12 requires `CONTRACTED`/`ON_TOUR` for a bed — members are built via `fx.contracted_member` so accepted stays are legitimately accepted.
2. `route_confirmation_errors_are_each_triggerable` gave its "Overloaded" stop `travel_miles_from_previous: 100` with no `previous_stop_id`, which PRD rung 5 refuses at creation; I added `previous_stop_id = origin_id` (134 travel minutes, still feasible, so the confirm fails on `ERR_INSUFFICIENT_TRUCKS` as intended).
3. Two instances assert "exactly one Season exists" but the PRD declares no `GET /seasons` collection route; substituted a direct season read.
4. `settlement_replay_sorts_by_recorded_at...` mislabels 56640 as the "5.5% tier" — the figure is right (4% of 1,416,000); I asserted the number and cited the PRD tier sentence.
5. `agreement_nights` is a phantom field; `billable_bed_nights` asserted instead. Where prose and the normative `assert:` block disagreed (third-delinquency cascade), the `assert:` block won.

`worklog.md` was not touched, and nothing was written or read under `workspace/`.

**Orchestrator verification:** `test_helpers/` and `test_suite/` are both at the task root; `find workspace -type d -name 'test_helpers' -o -name 'test_suite'` returned nothing, so no stray copies were written under `workspace/`.

## Step 7: Run Tests and Iterate — 2026-09-04T16:45:00.000Z

Clean sweep achieved. worklog.md untouched.

## Summary

**Iterations run:** 2

**Tests deleted:** none. All 6 failures traced to test-artifact bugs (4) and one implementation defect (1 rule, affecting 1 test). Every failing assertion passed STEP 1a coverage and STEP 1b unique-derivability.

**Fixes applied to `test_suite/`** (STEP 2 — test artifact was wrong, not the implementation):

- `test_suite/test_access_control.py`, `test_no_staff_role_may_reach_into_another_roles_exclusive_write` — removed a stray third positional argument (`BUSINESS_MANAGER_ID`) passed to `api.create_host_school(payload, headers)`. Pure syntax/arity bug; raised `TypeError` before any request was issued.
- `test_suite/test_contract_medical_and_agreement_machines.py`, `test_a_fourth_reissue_is_refused_and_strands_the_contract` — removed a stray fourth positional argument (`TOUR_MANAGER_HEADERS`) passed to `api.reissue_member_contract(contract_id, payload, headers)`. Same class of bug.
- `test_suite/test_resource_representations.py` — three creation-endpoint calls used `validate_success(response)`, whose runner default expects HTTP 200, against endpoints PRD §4 declares as `201 Created` ("Operations that bring a new resource into existence return `201 Created`"). Passed the explicit `201` in `test_a_new_season_opens_with_every_rollup_at_zero`, `test_client_supplied_values_for_derived_member_fields_are_discarded` and `test_the_four_common_properties_are_minted_by_the_server`. This makes the assertion *more* faithful to PRD, not less — one of the three already asserted `status_code == 201` on the line above, confirming intent.

No changes were needed in `test_helpers/`.

**Fixes applied to `implementation/`:**

- `workspace/implementation/routes/bookings.py`, `create_site_booking` (rung 39, `ERR_SITE_BLOCK_CONFLICT`) — the buffer window was expanded by 90 minutes instead of 180. PRD §3.7 states the buffer is "ninety minutes per side" on **both** sides of **every** block and then pins the boundary verbatim: "two blocks at one school must be separated by a clear gap of at least one hundred and eighty minutes; a gap of exactly one hundred and eighty minutes is accepted because the comparison is strict, and one of a hundred and seventy-nine minutes is refused with `ERR_SITE_BLOCK_CONFLICT`." The implementation only counted the existing block's buffer, so a 179-minute gap was wrongly accepted. Changed `buffer_delta` to `2 * BLOCK_BUFFER_MINUTES` so each block's own load-in/load-out both count; the strict `<` / `>` comparisons keep exactly 180 acceptable.

**Final sweep confirmation:** all 8 `results.$i.json` files (i = 1..8) report `passed == total == 106`, `failed == 0`, `errors == 0`. No flakiness across the 8 concurrent rounds — the original 6 failures were deterministic in all 8 rounds of iteration 1, and all 8 rounds of iteration 2 are green.

**Orchestrator independent verification:** re-read all 8 `results.$i.json` with a JSON parser (not trusting the subagent's report) — every round shows `passed=106 total=106 failed=0 errors=0`, all eight files written at 16:43, so the sweep artifacts are real and current. Step 8 will run (Step 7 applied 1 implementation fix, so the skip condition does not hold).

## Step 8: Finalize PRD — 2026-09-04T16:55:00.000Z

Done. `PRD_FINALIZED.md` written with one surgical edit.

## Line counts
- `PRD.md`: 501 lines; `PRD_FINALIZED.md`: 501 lines — **0.0% line delta** (one in-place sentence revision inside §3.7's line 310; +~50 characters).

## Changes
- **§3.7 (rehearsal-block buffer, rung 39 / `ERR_SITE_BLOCK_CONFLICT`)** — *revise* — the conflict formula now expands the existing block's window by **one hundred and eighty** minutes on each side instead of ninety, with the rationale made explicit ("each of the two blocks contributes its own ninety minutes"). This resolves PRD.md's internal contradiction: its formula sentence said ±90 while its very next sentence pinned a required clear gap of 180 with exactly-180 accepted and 179 refused. Impl: `implementation/routes/bookings.py:67` (`buffer_delta = timedelta(minutes=2 * BLOCK_BUFFER_MINUTES)`) and `:73-74` (strict `<` / `>`).

## Per-edit pre-edit search log
**Edit 1 — §3.7 buffer formula**
- (a) Subject: the load-in/load-out buffer window used to detect same-school rehearsal-block conflicts, and every place a booking's HELD/CONFIRMED status participates in that window.
- (b) Paths enumerated: `grep -rn "BUFFER\|buffer\|timedelta(minutes"` across all of `implementation/` — only two hits: `routes/bookings.py:17,62-76` (the sole buffer site) and `routes/stops.py:192` (travel-feasibility, unrelated arithmetic, untouched by my wording). Read `routes/bookings.py` in full: `create_booking` is the only endpoint that evaluates the buffer; the candidate set is filtered on `host_school_id` plus `status in ("HELD","CONFIRMED")` only — no agreement or stop scoping — so the existing PRD phrases "at the same school", "one whose `status` is `HELD` or `CONFIRMED`", and "Released blocks impose no buffer at all" all remain accurate and were left verbatim. Also checked every other path that reads booking status, to be sure no second buffer evaluation exists that my sentence would now mis-describe: `routes/stops.py:220` (stop-confirm promotes `HELD → CONFIRMED` with **no** conflict re-check), `services.py:65,125,137` (`booked_block_count` derivation and the stop-cancel / agreement-cancel release cascades). None re-evaluates the buffer, so scoping the sentence to the candidate-vs-existing comparison at creation stays correct.
- (c) Adjustment: kept the original "ninety minutes per side" clause rather than replacing it with a bare "one hundred and eighty minutes per side", and added the derivation clause, so the sentence stays consistent both with the constant actually named in the code (`BLOCK_BUFFER_MINUTES = 90`) and with the following, untouched "Equivalently … one hundred and eighty minutes" sentence.

## Step 7 items deliberately **not** patched
- The two arity bugs (`api.create_host_school`, `api.reissue_member_contract` extra positional args) are pure test-fixture defects with no behavioral content — no PRD silence.
- The three `validate_success` → explicit `201` fixes need no PRD change: §4 already states "Operations that bring a new resource into existence return `201 Created`", and I verified this holds globally, not just at the three test sites — all thirteen creation endpoints return 201 (`routes/{seasons,members,contracts,plans,payments,schools,agreements,housing,stops,bookings,volunteers,staffing,settlements}.py`, each `object_response(..., 201)`), while `envelope.object_response` defaults to 200 for every mutation/read. PRD prose kept verbatim.

## Step 9: Complete PRD — 2026-09-04T17:20:00.000Z

Run as **three sequential passes partitioned by implementation module**, all editing one shared `PRD_COMPLETED.md`. Pass 1 performed the single `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to re-copy. Partition: pass 1 = system + roster layer (`app/envelope/auth/errors/store/find/serialize/validators` + `routes/{clock,seasons,members,contracts}`), pass 2 = money/ledger (`calc.py`, `services.py`, `routes/{plans,payments,settlements}`), pass 3 = housing/tour logistics (`derive.py`, `routes/{schools,agreements,housing,stops,bookings,volunteers,staffing}`).

### Pass 1 — system + roster (21 edits: 17 ambiguity-pins, 4 mismatch-revisions)
501 lines / 105,879 chars → 502 lines / 113,394 chars (+1 line, +7,515 chars).
- §2.1 (headers) — insert — ambiguity — empty header value counts as absent; role strings compared case-sensitively — `auth.py:34`
- §2.1 (entity-backed roles) — insert — ambiguity — ownership compared on exactly three writes; entity-backed `X-User-ID` need not resolve to a record; reads never ownership-checked — `routes/contracts.py:19-22`, `routes/members.py:68`
- §2.2 (`api_request_id`) — insert — ambiguity — `req_` plus exactly 20 uppercase-alphanumeric characters — `envelope.py:18-19`
- §2.2 (`api_request_timestamp`) — insert — ambiguity — rendered from the logical clock, not wall time, on success and error alike — `envelope.py:22-26`
- §2.2 (error bullets) — insert (new bullet) — ambiguity — unknown path → `ERR_INVALID_REQUEST`/404, bad method → `ERR_INVALID_REQUEST`/405, both before authentication; trailing slash tolerated — `app.py:54-61`, `app.py:40`
- §2.3 (pagination) — insert — ambiguity — `limit`/`offset` rejected with `ERR_INVALID_REQUEST` rather than clamped; empty value = absent; over-range offset yields empty page; `created_at` ties broken by creation order — `envelope.py:53-84`, `store.py:146-148`
- §2.4 — insert — ambiguity — `updated_at` equals `created_at` at creation — `store.py:129-137`
- §2.4 (logical clock) — insert — ambiguity — `to_iso8601` required and must parse; capability returns 200 with empty `data` object — `routes/clock.py:21-24`
- §2.4 (datetime inputs) — insert — ambiguity — `Z`/offset/bare all accepted and normalised to UTC; unparsable → `ERR_INVALID_REQUEST`; client-supplied instants echoed byte-for-byte, only server-stamped instants use 3-digit `Z` form — `store.py:93-106`, `validators.py:106-127`, `routes/seasons.py:40-42`
- §2.5 (list filters) — insert — ambiguity — filters compared verbatim (unknown enum/id matches nothing rather than erroring), empty value = absent, undeclared params ignored, conjunctive, `is_minor` accepts `true/1/yes` case-insensitively — `validators.py:156-182`, `routes/members.py:77-91`
- §2.6 rung 3 — insert — ambiguity — explicit `null` counts as absent; absent/unparsable body treated as `{}`; non-object body is `ERR_INVALID_REQUEST`; booleans never integers; `year`/`tuition_base_cents`/`audition_score` range violations report `ERR_INVALID_REQUEST` at rung 3, not `ERR_AMOUNT_NOT_POSITIVE` at rung 6 — `validators.py:15-33`, `routes/seasons.py:26-27`, `routes/members.py:101`
- §2.6 rung 12 — revise — **mismatch** — contract execution's `OFFERED` gate is the one exception to this rung's position and is evaluated after rung 30; issuance carries no membership gate — `routes/contracts.py:140-150`, `routes/contracts.py:34`
- §3.1 — insert — ambiguity — `year`/`tuition_base_cents` violations are `ERR_INVALID_REQUEST` — `routes/seasons.py:26-27`
- §3.1 — insert — ambiguity — no uniqueness on `name`/`year`; five rollups re-derived on every read, not stored counters — `routes/seasons.py:34-54`, `serialize.py:108-109`
- §3.1 (`is_minor`) — insert — ambiguity — the 18-year shift clamps a 29 February departure date to 28 February — `store.py:118-123`
- §3.1 (audition) — insert — ambiguity — both fields required; score may be fractional, stored as supplied; out-of-range is `ERR_INVALID_REQUEST` — `routes/members.py:99-107`
- §3.1 (medical) — revise — **mismatch** — a call naming the current status is a legal no-op that still bumps `version`; `note` validated but never persisted; no membership-status gate — `routes/members.py:113-124`
- §3.2 (issuance) — revise — **mismatch** — `OFFERED` is not a server-enforced precondition on issuance; only rungs 6, 8, 48 gate it — `routes/contracts.py:27-39`
- §3.2 (revision/reissue) — insert — ambiguity — `revision_note` required on request-revision; reissued `tuition_amount_cents` type-checked only, not re-floored; reissue does not clear `revision_note` — `routes/contracts.py:82,98-113`
- §3.2 (signing) — insert — ambiguity — `signature_name` is a required string — `routes/contracts.py:122`
- §3.2 (execution) — revise — **mismatch** — three preconditions fire in written order (contract state → medical → membership standing); a non-`OFFERED` member reports `ERR_INVALID_MEMBER_STATE` — `routes/contracts.py:140-150`
- §3.5 (withdrawal payload) — insert — ambiguity — `withdrawal_date` required; `reason` validated as a string but recorded nowhere — `routes/members.py:131-132`

### Pass 2 — money / ledger (17 edits: 12 ambiguity-pins, 5 mismatch-revisions)
502 lines / 113,394 chars → 502 lines / 118,950 chars (all in-paragraph).
- §2.9 tuition chain — insert — mismatch — chain is live definitions, so posting/reversing money bumps no `version` except the payment's own and the plan's when its `status` moves; member and season never move — `services.py:10-36`, `routes/payments.py:66,107`
- §2.9 season rollups — insert — ambiguity — `tuition_collected_cents`/`late_fee_collected_cents` ignore plan status, so allocations on `SUPERSEDED`/`SETTLED`/`CLOSED_WITH_BALANCE` plans keep counting — `derive.py:199-208`
- §3.3 plan creation — insert — ambiguity — `expected_member_version` must be a JSON integer compared for exact equality; `first_due_date` has no range constraint, so a back-dated one makes installments immediately due/in arrears — `routes/plans.py:24-32`, `derive.py:41-50`
- §3.3 copied figures — insert — ambiguity — no rung-6 positivity floor re-applied, so a contract reissued to ≤0 finances a plan carrying that figure — `routes/plans.py:43,59`
- §3.3 derived plan figures — insert — ambiguity — `principal_paid_cents`/`late_fee_paid_cents` are live sums over that plan's `POSTED` payments; only `late_fee_accrued_cents`, `delinquency_strikes`, `status` are stored — `derive.py:53-74`
- §3.3 payment cascade — insert — ambiguity — member's `tuition_paid_cents` spans every plan the member ever held — `derive.py:90-96`
- §3.3 reversal — insert — ambiguity — only an `ACTIVE` plan can move; `DELINQUENT`/`CLOSED_WITH_BALANCE` stay put; a reversal never rewrites `late_fee_accrued_cents` or `delinquency_strikes` — `services.py:29-36`
- §3.3 reversal — insert — ambiguity — `reversal_reason` is a required string — `routes/payments.py:95`
- §3.4 sweep preamble — insert — ambiguity — five jobs run in the numbered order; season `version` advances by exactly one per sweep regardless — `services.py:153-237`
- §3.4 job one — insert — ambiguity — an `ACTIVE` plan with no arrears is left wholly untouched, `version` included — `services.py:164-168`
- §3.4 escalation — revise — **mismatch** — closure fires at `delinquency_strikes` of 2 or more (not "exactly 2"), count read is the pre-observation one, and `ACTIVE → DELINQUENT` is tested first, so a cured plan re-delinquent at 3 strikes closes only on a later sweep — `services.py:170-177`
- §3.4 link one — revise — **mismatch** — "the strike count reaches 3" softened to "advances by one, reaching 3 on the ordinary path" — `services.py:172,176`
- §3.4 link two — insert — **mismatch/ambiguity** — ejection fires only for a `CONTRACTED` member (an `ON_TOUR` member keeps standing, no obligation struck), and the internal `withdrawal_date` is subject to neither the future-dating gate nor the spring-start floor, so a pre-spring clock yields the admin fee alone — `services.py:178-182`, `calc.py:99-107`
- §3.4 job two — insert — ambiguity — the `CLOSED_WITH_BALANCE` bar covers any plan of the member's, and job one's results are already visible to job two — `services.py:184-200`
- §3.4 job five — insert — ambiguity — both conditions are universal quantifications, so a season with no stops reconciles on its first sweep; `RECONCILED` never reverts to `OPEN` — `services.py:226-235`
- §3.5 plan closure — revise — **mismatch** — plans close against the plan's own `outstanding_cents`, which the recharge does not move, making `CLOSED_WITH_BALANCE` the ordinary outcome — `services.py:75-86`, `derive.py:63-66`
- §3.9 placement bounds — insert — ambiguity — `>12` reports `ERR_INVALID_REQUEST` at rung 3 while `<1` reports `ERR_AMOUNT_NOT_POSITIVE` at rung 6, for both projected and final placement — `routes/settlements.py:26-30,122-125`
- §3.9 remittance lines — insert — ambiguity — `remittance_lines` required, must be an array (empty accepted), every line field required with rung-3 errors, `amount_cents` has no positivity floor and is used with whatever sign it carries, and lines are never persisted or echoed (only `remittance_line_count`) — `routes/settlements.py:89-114`

### Pass 3 — housing / tour logistics (16 edits: 12 ambiguity-pins, 4 mismatch-revisions)
502 lines / 118,950 chars → 502 lines / 122,785 chars (+3,835 chars, all inline).
- §2.8 — insert — ambiguity — `expected_facility_agreement_version` must arrive as a JSON integer, compared for exact equality — `routes/housing.py:32,39`
- §2.9 (housing chain) — insert — mismatch — housing-chain figures are live derivations, so a housing write moves only the assignment's and owning agreement's `version`; school and season never move — `derive.py:125-166`, `services.py:42-52`
- §3.6 (host schools) — revise — mismatch — `rehearsal_field_count` gates nothing; a school with 0 fields may still be booked for a rehearsal block — `routes/bookings.py:25-98`
- §3.6 (host schools) — revise — ambiguity — negative `rehearsal_field_count` and malformed `state_code` are `ERR_INVALID_REQUEST` at rung 3; only the two space figures reach rung 6 — `routes/schools.py:29-34`
- §3.6 (host schools) — insert — ambiguity — `booked_block_count`/`reserved_bed_nights` are live definitions (reserved sums across the school's agreements whatever their status), so the school's own `version` never advances — `derive.py:160-166`, `serialize.py:128-129`
- §3.6 (agreement drafting) — insert — ambiguity — negative `minimum_billable_beds` is `ERR_INVALID_REQUEST` at rung 3, not `ERR_AMOUNT_NOT_POSITIVE` — `routes/agreements.py:31,35`
- §3.6 (cancellation) — insert — ambiguity — `cancel_reason` is a required string — `routes/agreements.py:156`
- §3.6 (cancellation) — insert — ambiguity — the agreement's `version` advances exactly once for the whole demolition however many stays/blocks it released — `services.py:110-127`
- §3.6 (housing checks) — revise — ambiguity — rung 31 minor-mix outranks every later check (window, `space_index`, capacity, already-housed), not just capacity — `routes/housing.py:69-95`
- §3.6 (release) — insert — ambiguity — a hand or withdrawal release bumps both the assignment's and the agreement's `version`; only the cancellation path folds releases into one agreement bump — `services.py:42-61`
- §3.7 (stop planning) — insert — ambiguity — heat/count/`state_code` bounds are `ERR_INVALID_REQUEST` at rung 3 (stop planning never reaches rung 6); `rehearsal_minutes` has no bound and may be negative — `routes/stops.py:57-66`
- §3.7 (stop planning) — insert — ambiguity — the predecessor need not share the stop's season — `routes/stops.py:82-85`
- §3.7 (block booking) — revise — mismatch — the rung-18 agreement gate fires ahead of the rung-20 stop gate, and season-mismatch precedes school-mismatch — `routes/bookings.py:41-56`
- §3.7 (block booking) — insert — ambiguity — a block's instants are never compared against the parent stop's `arrive_at`/`depart_at` — `routes/bookings.py:25-98`
- §3.8 (volunteers) — insert — ambiguity — email compared verbatim/case-sensitively; `assignment_count` is a live derivation over `APPROVED` shifts, so the volunteer's `version` never moves on approval or release — `routes/volunteers.py:42-44`, `derive.py:176-177`, `serialize.py:148-150`
- §3.8 (screening decision) — insert — ambiguity — rung-22 state gate outranks the rung-44 future-dating gate — `routes/volunteers.py:91-98`
- §3.8 (approval) — revise — ambiguity — `assignment_count` rises as a consequence of the status move; only the shift's `version` advances — `routes/staffing.py:136-138`
- §3.8 (confirm) — revise — mismatch — the three coverage gates (rungs 32-34) fire ahead of the travel-time (38) and truck (55) checks the previous paragraph narrates first — `routes/stops.py:175-202`
- §3.8 (stop cancel) — insert — ambiguity — `cancel_reason` required string; released blocks/shifts each bump their own `version` while affected volunteers and schools bump none — `routes/stops.py:248`, `services.py:133-147`

### Orchestrator verification
- `PRD.md` 501 lines / 105,784 chars; `PRD_FINALIZED.md` 501 lines / 105,879 chars; `PRD_COMPLETED.md` **502 lines / 122,785 chars**.
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → DIFFERENT, and `diff` reports **99 changed lines** — the scan demonstrably ran (a byte-identical Step 9 output would have meant no scan happened).
- `tail` confirms `PRD_COMPLETED.md` terminates on a complete `## 5. Error Code Catalogue` row, not mid-sentence.
- `implementation/` was not modified by Steps 8 or 9, so the Step 7 sweep artifacts remain authoritative: all 8 `results.$i.json` at 106/106 passing.
- No stray `worklog.md` under `workspace/`; `test_helpers/` and `test_suite/` are at the task root.

**Pipeline complete through Step 9.**
