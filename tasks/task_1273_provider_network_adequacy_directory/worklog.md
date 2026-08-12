# Worklog — task_1273_provider_network_adequacy_directory

## Step 1: Create Task Directory — 2026-08-12T14:54:29.000Z

Pre-assigned output folder `tasks/task_1273_provider_network_adequacy_directory` with `workspace/` subdirectory already exists; Step 1 auto-index scan skipped per orchestration directive. Scenario: Provider Network Adequacy & Directory Accuracy (health plan network management). Difficulty parameter: "generate task hard than expert level!".

## Step 2: Generate Scaffold — 2026-08-12T16:03:30.000Z

Scaffold generation for task 1273 is complete and fully verified.

**Artifacts (all on disk at `/home/ubuntu/github/CodingPRD/tasks/task_1273_provider_network_adequacy_directory/`)**
- `SCAFFOLD.yaml` (§1.0–§1.7 only; neither design key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)

**Counts**
- 15 entities, 58 endpoints, 58 error codes, 9 calculations, 11 state machines, 11 validation priorities, 5 roles, 4 OCC concurrency rules (§1.2.1 schema, all 412)
- §1.8: 9 rules / 21 instances (dual-variant ×3 domains, combinatorial modes (a)+(b) with pre-computed literals 202480 / 89992, cyclic machines on AccessPlanRequest + DirectoryListing, depth-4 finalize cascade and depth-3 terminate cascade, 3 distinct priority-conflict pairs, 3 boundary metrics, 2 cross-entity pairs, half-open vs closed interval overlap, count vs money conserved quantities)
- §1.9: 57 instances across all 9 claim-guide sections (2 `excluded_because` stubs referencing real §1.8 instances)

**Difficulty-layer choices (beyond Expert)**: compliance/audit × posture-gating archetypes; layers = cascading side effects, dual-variant calculation, ops-run checkpoint (evaluation finalize epoch), optimistic concurrency; flat FK topology; cyclic state machines; segregation-of-duties role model (correction submitter ≠ verifier; NetworkManager files vs Regulator decides); logical clock `POST /_clock/set_current_utc` with pinned default 2026-05-01T00:00:00Z driving provider effective-date effectuation and all date gates.

**Verification**
- `scaffold_lint.py`: `VERDICT: clean lint` — 774 recipe calls scanned, all conform to §1.5; all 19 FKs reverse-reachable.
- Custom audit: every `grounds` ref resolves, zero unbound `${var}` placeholders, instance names unique across both files, every error code anchored in §1.4/§1.2/§1.2.1/§1.5, no forbidden concurrency vocabulary, endpoint roles ⊆ RBAC roles.
- Replay pass fixed 3 setup-ordering bugs (probe requested_date vs clock in two instances; late-attestation `responded_at > suppressed_at` strictness) and one formula wording (confirmed-error penalties counted for complaints that later auto-CLOSED).

## Step 3: Copy Shared Files — 2026-08-12T16:05:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1273_provider_network_adequacy_directory/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T16:14:07.000Z

# PRD Generation Summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1273_provider_network_adequacy_directory/workspace/PRD.md` — exists on disk, 320 lines (53,069 bytes).

**Constraint compliance:** Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced. No other `task_*/` directory was inspected.

## Hard-Contract Results

**Contract 1 — Field-Name Coverage: PASS**
- 122 required identifiers (entity fields + endpoint input keys + response-only outputs), 122 present, 0 missing
- One repair pass was needed: `to_iso8601` (the clock-set input) was added to §2.4
- Audit method: strip fenced code blocks (the §2.2 verbatim JSON fences would otherwise confuse the regex parity), then diff scaffold identifiers against PRD backticked tokens

**Contract 2 — Rule Coverage: PASS** (spot-check + enumeration)
- 39 targeted spot checks all pass: 4 OCC rules (each named with its `expected_*_version` field and `ERR_STALE_*_VERSION` id), 3-link terminate cascade, suspend/reinstate invariant, ghost-strike threshold = 3, cycle window ordering, NON_RESPONSIVE late-response path, p90 computation & non-gating semantics, all 8 penalty constants (9999 / 5,000,000 / 10,000 / 50,000 / 0.5 / 3 / 25,000 / 50,000), 72-hour SLA, 90-day filing window, `system:adjudication` sentinel, integer-arithmetic 90% time-distance gate, segregation of duties, both reason-specific reinstate errors, half-open cycle window, closed excuse window, 4-decimal response rate, RegionSpecialtyResult lacking `updated_at`/`version`, `listed_at`/`suppressed_at`/`finalized_at`/`submission_seq` stamps, evaluation singleton, logical clock default `2026-05-01T00:00:00Z`
- All 39 error IDs from `errors[]` appear verbatim
- All 5 role names appear verbatim
- All 31 state enumeration values appear in backticks

**Contract 3 — §3 Path Purity: PASS**
- 653 backticked tokens scanned in §3 (between `## 3.` and `## 4.`)
- 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos
- §3 refers to endpoints only via state-transition framing, role + action verb, or capability description

## Design Decisions

1. **§2 subsection skeleton (8 subsections, domain-derived):** 2.1 RBAC, 2.2 verbatim response envelope, 2.3 pagination, 2.4 common resource properties + logical clock, 2.5 precision/rounding/integer arithmetic, 2.6 OCC, 2.7 validation pipeline ordering, 2.8 coupled-spine cascade overview. The validation-pipeline and coupled-spine subsections are domain-specific (not generic boilerplate).
2. **§3 grouping (9 subsections, lifecycle + concern hybrid):** bootstrap (regions/standards/providers/locations), directory publishing, provider lifecycle, attestation cycles, attestation response + ghost detection, complaints + corrections, adequacy evaluation, access plan requests, member lifecycle. This mixes per-entity lifecycle with cross-cutting concerns (ghost detection is folded into §3.5 with probes rather than isolated) per the skill's grouping guidance.
3. **Calculation narrative style:** All formulas translated to prose without pseudocode — penalty accrual expressed as "base daily penalty of 9,999 cents multiplied by the day count, multiplied by the tier multiplier, multiplied by the repeat multiplier," p90 expressed as "the value at the 1-based index equal to the ceiling of nine-tenths of the sample size," and the 90% time-distance gate expressed as "ten times the compliant count being at least nine times the total."
4. **§4 / §5 tables:** 4 columns (Method/Path/Description/Roles) and 2 columns (Error ID/HTTP Status) respectively, per contract.

## Step 5: Generate Unit Tests — 2026-08-12T16:49:50.000Z

Generation complete and verified. Summary:

## Tests generated

**Queue A (Difficulty): 42 tests** — all 21 `scaffold_difficulty_design` instances covered with exactly 2 tests each, tagged `Design: Difficulty/<rule_id>/<instance.name>`. Zero skipped.

**Queue B (Corner): 54 tests** — 54 of 55 non-stub `scaffold_corner_design` instances covered with 1 test each, tagged `Design: Corner/<section>/<instance.name>`.

**Instances skipped (1):**
- `Corner/validations/create_listing_with_other_providers_location_rejected` — failed the **coverage** condition: the PRD names `ERR_LOCATION_PROVIDER_MISMATCH` only as the second of the four *publish*-time checks (§3.2); it never states that the coherence check also fires at listing *create* time, so a PRD-only implementer could legitimately accept the POST and reject at publish. Per the `applies_to-scope` silence pattern, the instance was skipped rather than weakened.

**Stubs not translated (2):** `ghost_strike_auto_under_review_covered_by_difficulty` and `provider_effectuation_sweep_covered_by_difficulty` — both `excluded_because:` stubs whose difficulty-instance cross-references were verified to resolve.

**Total: 96 tests**, collected cleanly by pytest.

## test_helpers/ files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1273_provider_network_adequacy_directory/test_helpers/`)
`types.py` (14 entity TypedDicts — RegionSpecialtyResult correctly omits `updated_at`/`version` per common_fields:false — 18 status/role enums), `api_client.py` (41 endpoint methods covering every PRD §4 row incl. `/_clock/set_current_utc` and penalty-summary), `api_errors.py` (full 47-code catalog with HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity asserts + `assert_deficiency_money_invariant`), `factories.py` (13 payload factories with collision-free npi/fips/member_ref counters), `constants.py` (penalty tiers, caps, ghost threshold, 72h SLA, 90-day window), `test_users.py` (5 role header constants + `make_provider_rep_headers`/`make_member_headers` entity-backed builders used for all ownership-gated calls), `fixtures.py` (tiered composites: `setup_listed_network`, `setup_provider_with_n_listings`, `setup_open_deficiency`, `setup_open_cycle_for_listings`, `respond_record`, `setup_complaint`, `confirm_complaint`, etc.), and `__init__.py` barrel.

## Verification performed
- `python -m py_compile` on all 18 files: OK
- pytest collect: 96 tests, no import/fixture errors
- Scripted audit: every test has exactly one Design tag resolving to a real instance; all 21 difficulty instances have ≥2 tests; all 54 translated corner instances have ≥1; every PRD citation in every docstring is verbatim-present in `workspace/PRD.md` (whitespace-normalized containment check): **zero problems**.

## Step 6: Generate Implementation — 2026-08-12T16:49:50.000Z

Implementation complete. Final summary:

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1273_provider_network_adequacy_directory/workspace/implementation/`)

- `start.sh` — executable; guards `pip install` behind a `python3 -c "import flask"` check, then `exec python3 app.py` (foreground, `0.0.0.0:$PORT`, default 10000)
- `requirements.txt` — flask>=3.0
- `app.py` — Flask entry point, blueprint registration, error handlers
- `db.py` — in-memory stores (dicts keyed by id) + logical clock initialized to exactly `2026-05-01T00:00:00Z`; **no seeding anywhere**
- `errors.py` — all 52 catalogued error IDs with exact HTTP statuses
- `response.py` — envelope: `meta.api_request_id` (`req_…`), `meta.api_request_timestamp` (3-fractional-digit ISO), `response_type`, `data`; pagination fields `limit/offset/total_count/has_more` in `meta`
- `middleware.py` — `X-User-ID` / `X-User-Role` extraction, 5 recognized roles, per-endpoint RBAC
- `helpers.py` — serializers, pagination (created_at ASC, limit default 10 / min 1 / max 100), field/enum/date validation, clock helpers
- `routes/` — 16 modules: clock, regions, standards, providers, locations, listings, members, cycles, records, probes, evaluations, results, deficiencies, access_plans, complaints, corrections
- `services/` — `cascades.py` (provider suspend/reinstate/terminate 3-link cascade, listing-removal record cancellation, cycle counter recompute, clock effectuation sweep), `ghost.py` (chronological consecutive-FAIL replay, threshold ≥3 → UNDER_REVIEW), `finalize.py` (4-link evaluation cascade)

## Route count verification

Programmatic diff of Flask's url_map against SCAFFOLD.yaml §1.5: **58 declared, 58 registered, 0 missing, 0 extra** — exact (method, path) parity including `POST /_clock/set_current_utc`.

## Key design decisions

- **Logical clock only**: all timestamps/dates read `db.clock_now`; business entities are stamped with the logical clock while envelope `meta` uses wall time. Clock-set returns `current_utc` + `effectuated_provider_ids` and sweeps PENDING_LOAD → EFFECTIVE.
- **OCC on the 4 guarded writes** runs immediately after path-id resolution and before all business logic (412 errors: stale standard/location/listing/deficiency).
- **PRD precedence applied**: manual reinstate of a `PROVIDER_SUSPENDED`-suppressed listing raises `ERR_LISTING_INVALID_TRANSITION` unconditionally (checked before the provider-EFFECTIVE guard), per PRD §3.2's unconditional wording.
- **Exact arithmetic**: Decimal ROUND_HALF_UP per accrual event before summation; tiered penalty (9999¢/day base, 1.0/1.5/2.0 tier by enrolled count, repeat multiplier 1 + 0.5·min(prior_closures, 3), 5,000,000¢ cap); integer 10·ok ≥ 9·total for the 90% time/distance gate; p90 via 1-based ceil(0.9N) index; response rates at 4dp with 0/0 → null; `outstanding = accrued − reversed` invariant.
- **RegionSpecialtyResult** serialized without `updated_at`/`version` (immutable snapshot); cycle serializer exposes strict and lenient response-rate variants.
- **Reopen branch**: EXCUSED deficiency whose latest APPROVED `excuse_through_date < period_end_date` reopens with accrual window `max(period_start, excuse_through) .. period_end`; access-plan approval reverses outstanding penalty and decrements both `total_penalty_cents` and `deficiency_penalties_cents` on the owning evaluation.

## Verification performed

Two smoke suites (~95 assertions) run against live boots covering auth/RBAC, all CRUD, OCC 412s, publish precondition ordering, ghost-strike → UNDER_REVIEW → clear, manual/provider suspend-reinstate cascades, terminate 3-link cascade, cycle windows/adjacency/advance sweeps, late attestation response + reinstate guards (strict `responded_at > suppressed_at`), probe date-order and inclusive PASS boundary, URGENT exclusion from the official wait gate, finalize block on SCHEDULED probes, deficiency accrual (299,970¢ = 9999×30 verified), EXCUSED row status, penalty-summary shape and reversal decrement, complaint 90-day window boundaries, correction spawn/verify/SoD/reject, and complaint closure cascade. Both suites pass from fresh boots; a fresh boot returns empty lists (no seeding). All files compile; `start.sh` is executable (`-rwxrwxr-x`); `workspace/implementation/` exists on disk.

## Step 7: Run Tests and Iterate — 2026-08-12T17:00:30.000Z

## Summary

- **Iterations run:** 2 (sweep 1: 3 deterministic failures × 8 rounds, no flakiness; fixes applied; sweep 2: all 8 rounds 96/96).

- **Tests deleted:** none. Both failure classes traced to PRD-verbatim-covered rules, so deletion was never on the table.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1273_provider_network_adequacy_directory/test_helpers/fixtures.py`, `setup_provider_with_n_listings` — the per-location default `address_line=f"{i+1} Fixture Ave"` was passed as an explicit kwarg alongside `**loc_over`, so any `location_overrides_list` entry containing `address_line` raised `TypeError: got multiple values for keyword argument 'address_line'`. Merged as `**{"address_line": default, **loc_over}` so caller overrides win, matching the fixture's documented override contract. Fixed `test_provider_count_counts_distinct_providers` and `test_official_headcount_governs_overall_status`.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1273_provider_network_adequacy_directory/test_suite/test_06_evaluations_adequacy.py`, `TestPenaltyTierRepeatInterplay._setup_reopened_pair` — `d1` was the stale response snapshot fetched at E1 finalize; E2's compliant finalize closes D1 server-side (PRD §3.7 Link 2: "each pair that came out `COMPLIANT` and has an existing `OPEN` or `EXCUSED` deficiency has that deficiency transitioned to `CLOSED` with `closed_date` set to `period_end_date`"). Added a re-fetch via `get_deficiency(d1["id"])` after the E3 finalize so `status`/`closed_date` assertions read current server state. The implementation was already correct — the sibling test (`test_reopened_deficiency_stacks_tier_and_repeat_multipliers`, asserting `prior_closure_count == 1` on D2) only passes if D1 is actually CLOSED.

- **Fixes applied to `implementation/`:** none — the implementation was faithful to PRD on all three failures.

Orchestrator verification: all 8 `results.{1..8}.json` exist on disk; every round reports `passed == 96 == total`, `failed == 0`.

## Step 8: Finalize PRD — 2026-08-12T17:03:10.000Z

Done. PRD_FINALIZED.md is an exact copy of PRD.md — zero edits were required.

## Verification of each step_7_diff item

**Item 1 — `test_helpers/fixtures.py`, `setup_provider_with_n_listings` (fixture fix):** Pure Python bug, not a PRD silence. The per-location default `address_line` was passed as an explicit kwarg alongside `**loc_over`, raising `TypeError` whenever an override entry contained `address_line`; the fix (`fixtures.py:192-194`, `**{"address_line": default, **loc_over}`) is entirely test-side. The implementation's location contract (`implementation/routes/locations.py:20,31` — required `address_line` at create, optional at patch via `:84-86`) is already covered verbatim by PRD line 104. No PRD edit.

**Item 2 — `test_suite/test_06_evaluations_adequacy.py`, `_setup_reopened_pair` (test fix):** Stale-snapshot test bug; implementation was already PRD-correct. PRD §3.7 Link 2 (PRD.md line 170) already states verbatim: "each pair that came out `COMPLIANT` and has an existing `OPEN` or `EXCUSED` deficiency has that deficiency transitioned to `CLOSED` with `closed_date` set to `period_end_date` and `version` incremented." The implementation matches exactly at `implementation/services/finalize.py:279-284` (`d["status"] = "CLOSED"`, `d["closed_date"] = evaluation["period_end_date"]`, `helpers.touch(d)` bumps version). No PRD edit.

**Item 3 — `implementation/` fixes:** none applied, per the diff summary.

## Summary on exit

- **Line counts / %-delta:** PRD.md = 320 lines, PRD_FINALIZED.md = 320 lines; delta 0.0% (files byte-identical, confirmed by `diff`).
- **Changes:** none — no insert or revise bullets to report.
- **Per-edit pre-edit search log:** no edits were committed, so no edit-triggered searches apply. The two read/grep investigations above served as the consistency check for the decision to not edit:
  - (a) Subject candidate 1: `address_line` on location create/patch — (b) paths enumerated: `implementation/routes/locations.py:20,31,84,86`, `implementation/helpers.py:257` (response serialization) — (c) conclusion: PRD line 104 already uniquely determines the behavior; fixture default merging is out of PRD scope.
  - (a) Subject candidate 2: deficiency closure on COMPLIANT finalize — (b) paths enumerated: `implementation/services/finalize.py:279-284` (COMPLIANT branch), `:237-277` (DEFICIENT branches: create/extend/reopen, confirming no other path closes deficiencies), sibling test `test_reopened_deficiency_stacks_tier_and_repeat_multipliers` asserting `prior_closure_count == 1` on D2 — (c) conclusion: PRD §3.7 Link 2 already covers this verbatim; the test fix only re-fetched server state.

File produced: `/home/ubuntu/github/CodingPRD/tasks/task_1273_provider_network_adequacy_directory/workspace/PRD_FINALIZED.md`.

## Step 9: Complete PRD — 2026-08-12T17:22:47.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1273_provider_network_adequacy_directory/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`.

**Size:** PRD_FINALIZED.md = 320 lines / 53,069 chars; PRD_COMPLETED.md = 320 lines / 58,360 chars (char-delta +5,269, line-delta 0 — all changes are in-paragraph inserts/revisions; no new sections).

**Counts:** 22 ambiguity-pins, 3 mismatch-revisions (25 changes total).

**Changes:**
- §2.1 — insert — ambiguity — empty-string `X-User-ID`/`X-User-Role` counts as missing → `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` — middleware.py:21
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; `created_at` ties broken by `id` ascending; `has_more` ≡ `offset + len(returned) < total_count` — helpers.py:165-193, response.py:43
- §2.4 — insert — ambiguity — entities created with `version` 1 and `updated_at` = `created_at`; cycle-counter and `ghost_strike_count` recomputations exempt from version bump — helpers.py:200-213, services/cascades.py:7-25, services/ghost.py:25-28
- §2.4 — insert — ambiguity — clock-set input format (strict `...Z` ISO 8601, else `ERR_INVALID_REQUEST`); no monotonicity guard — routes/clock.py:19-21, helpers.py:32-57
- §2.4 — insert — ambiguity — all entity/workflow timestamps read the logical clock; only the envelope's `api_request_timestamp` is wall-clock — helpers.py:35-41, response.py:17-20
- §2.6 — revise — ambiguity — expected-version field is required on the four OCC endpoints (missing/non-integer → `ERR_INVALID_REQUEST`); other endpoints ignore version fields — routes/standards.py:71, locations.py:74, listings.py:127, access_plans.py:24
- §2.7 — insert — ambiguity — unknown result id on `GET /network/results/{id}` → `ERR_INVALID_REQUEST` (400), no result-specific 404 — routes/results.py:39
- §3.1 — insert — ambiguity — `enrolled_member_count` must be a non-negative integer — routes/regions.py:21-23
- §3.2 — insert — ambiguity — listing create enforces `location.provider_id == provider_id` (`ERR_LOCATION_PROVIDER_MISMATCH`) at create time — routes/listings.py:41-42
- §3.2 — insert — ambiguity — publish requires current status `DRAFT`, else `ERR_LISTING_INVALID_TRANSITION` before the four checks — routes/listings.py:89-90
- §3.2 — insert — ambiguity — `suppress_reason` allowed values and interplay with `to_status` (required-in-effect on SUPPRESSED, rejected on LISTED, ignored on REMOVED); `to_status=LISTED` valid only from `UNDER_REVIEW`/`SUPPRESSED`; clear-review/reinstate require provider `EFFECTIVE`; `suppressed_at` stamped on every SUPPRESSED entry and retained (with `listed_at`) across reinstate — routes/listings.py:130-207
- §3.2 — insert — ambiguity — already-`SCHEDULED` probes may still be recorded after listing removal; cannot transition a `REMOVED` listing — routes/probes.py:79-119, services/ghost.py:26
- §3.3 — insert — ambiguity — provider PATCH body field `to_status` ∈ {`SUSPENDED`,`EFFECTIVE`,`TERMINATED`}, else `ERR_INVALID_REQUEST` — routes/providers.py:75
- §3.4 — revise — **mismatch** — dropped "(unique)": `cycle_label` uniqueness is not enforced (no duplicate-label error exists) — routes/cycles.py:21-44
- §3.4 — insert — ambiguity — cycle read model exposes `response_rate_strict`, `response_rate_lenient`, and `response_rate` (strict alias) — helpers.py:306-317
- §3.5 — insert — ambiguity — non-`KEPT` record with `offered_appointment_date` supplied → `ERR_INVALID_REQUEST` — routes/probes.py:97-99
- §3.6 — insert — ambiguity — complaint filing with unknown Member id → `ERR_NOT_RESOURCE_OWNER` (403) — routes/complaints.py:24-26
- §3.6 — insert — ambiguity — correction verification still applies (changes, flag clear, version bump) when the listing has since become `REMOVED` — routes/corrections.py:112-124
- §3.7 — insert — ambiguity — finalize guard order: `OPEN`-state check before unrecorded-probe sweep — routes/evaluations.py:70-79
- §3.7 — revise — **mismatch** — probed set is `ROUTINE`-only `KEPT` probes; `URGENT` excluded from `probed_listing_count`/`mean`/`p90`/gate entirely (PRD had defined the set type-agnostic) — services/finalize.py:117-128
- §3.7 — insert — ambiguity — each accrual event re-stamps `accrual_window_start`/`accrual_window_end` — services/finalize.py:208-209
- §3.7 — insert — ambiguity — deficiency `evaluation_id`: set at creation, updated on reopen-from-`EXCUSED`, unchanged on extension — services/finalize.py:245,263-267,273
- §3.7 — insert — ambiguity — penalty-summary row shape (`kind`=`DEFICIENCY_ACCRUAL`, `deficiency_id`, `region_id`, `specialty`, `amount_cents`); rows cover accrual events only; pre-finalize summary returns zeros/empty — routes/evaluations.py:90-107
- §3.8 — insert — ambiguity — approval also decrements evaluation's `deficiency_penalties_cents` (floored at 0) and bumps evaluation `version` — routes/access_plans.py:139-142
- §3.8 — revise — **mismatch** — `DENIED` also records optional `notes` in `decision_notes` (PRD said "simply stamps decided_at") — routes/access_plans.py:143-147
