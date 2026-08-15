# Worklog — task_1541_sports_agency_contract_cap_management

## Step 1: Create Task Directory — 2026-08-13T18:54:00.000Z

Task directory `tasks/task_1541_sports_agency_contract_cap_management/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-13T19:25:00.000Z

## Report

Generated the complete scaffold for **task_1541_sports_agency_contract_cap_management**.

### Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1541_sports_agency_contract_cap_management/SCAFFOLD.yaml` — §1.0–§1.7 (response envelope, entities, state machines, calculations, validations, endpoints, errors, RBAC). No `scaffold_difficulty_design` or `scaffold_corner_design` keys.
- `/home/ubuntu/github/CodingPRD/tasks/task_1541_sports_agency_contract_cap_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` key with 18 instances (2 per each of the 9 difficulty rules).
- `/home/ubuntu/github/CodingPRD/tasks/task_1541_sports_agency_contract_cap_management/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` key with 32 instances across 7 sections (entities / state_machines / calculations / validations / endpoints / errors / rbac / cross-cutting layers).

### Design choices
- **Archetype:** `compliance_audit` primary, `quota_allocation` secondary.
- **Layers:** optimistic_concurrency, cascading_side_effects, dual_variant_calculation, scheduled_actions.
- **Topology:** hierarchical (Agency → Agent/Client → Contract/Endorsement → Proposal/TenderOption/Grievance), with cross-aggregate CapSeason/Team.
- **State machines:** 7 machines — Agent (branching with REVOKED terminal), Client (ACTIVE/TRANSITIONING/RELEASED), Contract (parallel dimensions signing × cap_posting), Proposal (cyclic SUBMITTED↔COUNTERED), EndorsementDeal (linear with auto-complete), TenderOption (windowed), Grievance (branching with revert loop), CapSeason (OPEN/LOCKED/CLOSED).
- **Calculations:** contract_aav (per-year rounding then sum — pinned order), endorsement_agent_fee (tiered then cap), contract_fee_accrual, transition_split_fee (25/75 waterfall with residue to new agent), cap_space_projection, escalator_projection.
- **Endpoints:** 76 (agency/team/cap-season setup, nested contract+proposal+tender+grievance+endorsement actions, fee-ledger reads, plus flat reverse-reachability GETs at `/agents`, `/clients`, `/cap_seasons`, `/contracts`, `/proposals`, `/endorsements`, `/tender_options`, `/grievances`, `/fee_ledger_entries`, plus `/_clock/set_current_utc` with default 2026-08-01T00:00:00Z).
- **RBAC:** 5 roles — LeagueOfficer (opaque), AgencyManager (entity_backed:Agent with is_manager=true), Agent (entity_backed:Agent), Team (entity_backed:Team), Player (entity_backed:Client, read-only).
- **Errors:** 15 domain-specific error codes.

### Lint verdict
`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`
Coverage: 76 endpoints, 11 entities, 18 difficulty instances, 32 corner instances, 591 calls scanned. Zero violations.

### Notable fixes applied during iteration
- Converted `grounds:` inline flow sequences in corner design to block sequences (YAML parse issue with nested `[` `]`).
- Added 18 flat top-level GET list endpoints to satisfy FK reverse-reachability (lint check (f) requires paths under the `api_prefix` to anchor entity collection segments).
- Set `api_prefix: ""` (empty) so the lint heuristic recognizes both nested `/agencies/{aid}/...` paths and flat `/<collection>/{id}` retrieval paths.
- Replaced "in parallel" wording in one difficulty `distinguishing_aspect` (forbidden vocabulary per §1.2.1).

## Step 3: Copy Shared Files — 2026-08-13T19:26:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1541_sports_agency_contract_cap_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T19:47:00.000Z

## Summary

Generated a complete PRD from the scaffold (the two forbidden design files were not opened). Document structure:

- **§1 Introduction** — 2 paragraphs (business context angle, then system scope).
- **§2 Global Specifications** — 9 subsections: 2.1 RBAC with per-role identity translations (LeagueOfficer opaque; AgencyManager/Agent entity-backed by Agent; Team by Team; Player by Client), 2.2 verbatim response envelope (byte-identical, verified), 2.3 pagination (`limit` 10/1–100, `offset` 0, `created_at` ascending), 2.4 common properties (UUID `id`, ISO 8601 `created_at`/`updated_at`, `version` incrementing incl. cascade mutations), 2.5 logical clock (boots 2026-08-01T00:00:00Z, never wall-clock, `to_iso8601`/`current_utc`), 2.6 integer-cents + round-half-up precision, 2.7 left-to-right path resolution + the full 14-step validation pipeline in priority order with an explicit masking example, 2.8 committed/reserved cap ledger with `available_hard_cents`/`available_luxury_cents`, 2.9 OCC for the two guarded writes.
- **§3 Business Logic** — 9 subsections (agency/certification, roster transitions & release, teams/cap seasons, contract valuation, negotiation cycle, signing/voiding, tender windows, endorsements, grievances + fee ledger), rules scattered via state-transition framing; no paths or methods.
- **§4** — 76 endpoints, 4 columns (Method, Path, Description, Authorized Role(s)). **§5** — 15 error IDs, 2 columns.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 55 required, 55 present, 0 missing
- endpoints[].request_body: 52 required, 52 present, 0 missing
- endpoints[].query_params: 19 required, 19 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 14 checked, 14 expressed in prose (ordered pipeline + masking example), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write op + expected_cap_season_version / expected_contract_version + ERR_STALE_VERSION 412, no race framing), 0 missing
- state_machines[].transitions: 35 checked, 35 fully expressed, 0 missing
- calculations[]: 6 checked, 6 fully expressed (precise prose, per-step rounding pinned, tier boundaries with inclusivity, 25/75 split with residue to new agent), 0 missing
- validations[] conditions: 14 checked, 14 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all checked and expressed (sign/void/suspend/revoke/lock/accept cascades, cert-gate and ownership scopes enumerated), 0 missing
- entities[].fields[] structured content: 55 checked, defaults/nullability/invariants reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (withdraw ×3, revoke ×2, release ×2, void ×2, close ×2, grievance withdraw ×2, counter/resubmit, complete/terminate), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 325
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verified hygiene: all 41 enum/state strings present as exact UPPERCASE tokens, all 15 error IDs appear in §2/§3 narrative, no pseudocode operators (`==`, `<=`, `+=`, `min()`, etc.) leaked into prose, no fuzzy/approximating words, all 76 scaffold endpoint paths present in §4, and the document ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-13T20:18:00.000Z

Test generation for task_1541 is complete and fully audited.

**Stage 1 — `test_helpers/`** (9 files, imports verified):
- `types.py` — 11 entity TypedDicts + 11 status enums + `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with all 56 PRD §4 endpoints (agency/agent/client/team/cap-season/contract/proposal/endorsement/tender/grievance/fee-ledger, the logical-clock endpoint, and the flat LeagueOfficer reverse-reachability views)
- `api_errors.py` — all 15 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` (all entities carry common fields per §2.4) + cap-season counter invariant checker
- `factories.py`, `constants.py` (fee tiers 0.10/0.15/0.20, splits 0.25/0.75, MAX_YEARS=5, MAX_ESCALATOR=0.15, boot clock 2026-08-01), `test_users.py` (opaque LeagueOfficer constant + per-instance `make_*_headers` builders for the four entity-backed roles)
- `fixtures.py` — composite chains: `setup_negotiation_env` (agency→manager self-certify→agent→client→team→cap season), `create_contract`/`create_draft_proposal`, OCC-correct `submit_proposal`/`sign_contract` (fresh version re-read before every versioned write), `sign_contract_via_proposal`, `setup_signed_contract`, endorsement/tender/grievance helpers, and ledger query helpers

**Stage 2 — `test_suite/`** (7 files, 68 tests, all collected by pytest):
- `test_01` agency/agent certification + auth + suspend cascade; `test_02` client listing, release gates, transition fee splits, sign gating; `test_03` AAV valuation, field constraints, pair uniqueness, parallel dimensions, void cascade; `test_04` proposal cycle, hard/soft cap boundaries, season gating, reserved invariant, OCC, fee accrual; `test_05` tender windows + clock; `test_06` endorsement fee tiers; `test_07` grievances + ledger reads.

**Audit results (all clean):**
- Coverage: all 18 difficulty instances have ≥2 tests; all 32 non-stub corner instances have ≥1; the one `excluded_because` stub's cross-reference resolves and was not translated
- Tags: exactly one `Design:` line per test, at docstring end, verbatim-resolving to a real instance; zero untagged/dual-tagged
- Citations: all 68 docstring quotes survive literal grep of PRD.md
- No `skip`/`skipif`/`xfail`, no scaffold references in generated code

**Notable adjudications:** (1) exercise-at-exactly-`window_close_at` uses `validate_error_is_one_of([ERR_WINDOW_CLOSED, ERR_INVALID_STATE])` — the auto-expiry at the same instant makes the error_id non-uniquely-derivable (error-precedence silence pattern); (2) the corner agency-creation assertion of `version == 1` was dropped because PRD §2.4 never pins the initial version value — the test asserts only PRD-covered claims (status, id, created_at); (3) two priority-pair instances were paired with isolation tests showing the lower-priority error firing alone; (4) the transition-split residue case uses fee_cap 0.01 / aav 30,000,200 → remaining_fee 300,002 (≡2 mod 4), which distinguishes residue-to-incoming-agent (225,001) from naive independent rounding (225,002).

## Step 6: Generate Implementation — 2026-08-13T20:18:00.000Z

Implementation complete. All files are in `/home/ubuntu/github/CodingPRD/tasks/task_1541_sports_agency_contract_cap_management/workspace/implementation/`:

**Files produced**
- `app.py` (~1,250 lines) — all 60+ endpoints: clock, agencies, agents (certify/suspend/reinstate/revoke), clients (transitions/release), teams, cap seasons (lock/unlock/close), contracts (sign/void), proposals (submit/counter/resubmit/accept/reject/withdraw), endorsements (approve/terminate), tender options (exercise), grievances (full adjudication chain), fee ledger (list/get/mark_paid), plus all 18 flat LeagueOfficer reverse-reachability reads
- `db.py` — in-memory stores + logical clock booting at 2026-08-01T00:00:00Z, never wall-clock
- `errors.py` — all 15 catalog error IDs with exact HTTP statuses
- `response.py` — scaffold-exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in meta; error body `error_id`/`message`)
- `helpers.py` — auth (`X-User-ID`/`X-User-Role`, 5 declared roles), body validation, pagination (limit 1–100 default 10, offset), left-to-right scoped path resolvers, `bump_once` for one-version-bump-per-entity-per-request cascades
- `services.py` — calculations in `Decimal` with ROUND_HALF_UP at exactly the scaffold-specified steps: contract AAV (per-year base rounding → prorated bonus/incentive rounding → per-year cap-hit sum → final AAV division), tiered endorsement fee (10/15/20% at $1M/$5M lines, then min with agency cap), playing-contract fee, transition 25/75 split with rounding residue to the new agent
- `start.sh` — guarded pip install (no-op once flask present), `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask

**Key semantic decisions (PRD-faithful)**
- All server timestamps (`created_at`, `certified_at`, `exercised_at`, envelope timestamp) derive from the logical clock per PRD §2.5's "never fall back to wall-clock time"
- Validation pipeline strictly ordered per PRD §2.7: notably soft-cap (step 8) and hard-cap (step 9) outrank resource-lock (step 10), so a luxury-breaching submit on a LOCKED season returns `ERR_CAP_WOULD_EXCEED`, not `ERR_RESOURCE_LOCKED`
- OCC fields (`expected_cap_season_version` on submit, `expected_contract_version` on sign) are required (400 if missing), checked right after existence; proposal **acceptance bumps the contract's version** per scaffold §1.2.1's stale-signer scenario
- Time-driven transitions (endorsement COMPLETED at `end_date`, tender EXPIRED at `window_close_at`) run as a lazy sweep before every request — so exercise-after-close surfaces 409 `ERR_INVALID_STATE` (record already EXPIRED), while exercise-before-open surfaces 422 `ERR_WINDOW_CLOSED`
- Client registration and `initiate_transition` enforce the CERTIFIED-primary/successor gate per PRD §3.2 prose; withdraw endpoints check ownership only (no cert gate), matching scaffold `applies_to`

**Verification** — two ad-hoc suites run against fresh boots: 87/87 main-flow checks and 47/47 edge-case checks passed (auth/RBAC, precedence masking, OCC 412s, cap arithmetic with exact cent values, all cascades, tier boundaries, release gates, pagination). Per-test-server isolation confirmed: kill + relaunch yields an empty store, clock reset to 2026-08-01, HTTP-ready in ~0.9s, and literal `bash start.sh` from `./implementation/` works. No entities are seeded at startup.

## Step 7: Run Tests and Iterate — 2026-08-13T20:35:00.000Z

## Summary

**Iterations run:** 2 (initial sweep → 4 deterministic failures → fixes → clean 8/8 sweep, 68/68 per round).

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule; no PRD-silence or unique-derivability deletions were warranted.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1541_sports_agency_contract_cap_management/test_suite/test_02_client_roster_transitions.py` — added missing `create_draft_proposal` import (both `TestSignGatedByClientState` tests died with `NameError`; pure test-authoring bug, not a PRD question).
- `/home/ubuntu/github/CodingPRD/tasks/task_1541_sports_agency_contract_cap_management/test_suite/test_03_contracts_valuation.py` — `test_contract_aav_nested_rounding_order`: the docstring's worked arithmetic had an addition slip (10,000,000 + 500,001 + 250,001 = 10,750,002, written as 10,750,001), so the asserted `aav_cents == 11_125_001` mis-translated the PRD §3.4 formula it quotes verbatim. Corrected expected value to `11_125_002` (cap hits 10,750,002 / 11,500,002; total cap hits 22,250,004) — the value the PRD formula uniquely yields and the implementation already computed.
- `/home/ubuntu/github/CodingPRD/tasks/task_1541_sports_agency_contract_cap_management/test_suite/test_05_tender_options_and_clock.py` — `test_intruder_agent_and_closed_window_yields_ownership_violation`: window closes before the boot clock, so PRD §3.7's auto-expiry ("the system itself moves the record from PENDING to EXPIRED") races the pipeline; under PRD §2.7 an already-EXPIRED record trips state (step 4) before ownership (step 6). Error-precedence silence — relaxed to `validate_error_is_one_of([ERR_OWNERSHIP_VIOLATION, ERR_INVALID_STATE])`, matching the sibling test's existing pattern (the explicitly permitted coverage correction, not a downgrade).

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1541_sports_agency_contract_cap_management/workspace/implementation/helpers.py` — `get_json_body` now parses request JSON with `json.loads(..., parse_float=Decimal)` and `_is_number` accepts `Decimal`, so rate fields (`fee_cap_pct`, `escalator_pct`) are carried as exact decimal fractions end-to-end per PRD §2.6 ("Rates and percentages are exact decimal fractions") rather than transiting binary float64.
- `/home/ubuntu/github/CodingPRD/tasks/task_1541_sports_agency_contract_cap_management/workspace/implementation/app.py` — `view()` serializes `Decimal` fields back to plain JSON numbers (int if integral, else float) so responses stay standard JSON; escalator bounds check compares against exact `Decimal("0.15")`.

**Notes:** the mid-run console grep during iteration 1 showed phantom FAILED lines for two valuation tests that all 8 results files record as passed — the authoritative per-round `results.*.json` files (4 identical failures × 8 rounds) drove the diagnosis. No seeding, no persistence, and no non-PRD behavior was added; storage remains in-memory dicts only.

## Step 8: Finalize PRD — 2026-08-13T20:44:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1541_sports_agency_contract_cap_management/workspace/PRD_FINALIZED.md` produced as a 2-edit minimal patch of PRD.md.

**Line counts:** PRD.md 279 lines; PRD_FINALIZED.md 279 lines (both edits are inline sentence insertions into existing paragraphs; two lines changed in place, no lines added or removed; 0% line-count delta).

**Changes:**
- §2.5 (Logical Clock) — insert — pinned that automatic time-driven transitions (tender-option expiry, endorsement completion) are applied as the first step of processing every request, before the validation pipeline runs, so a past-`window_close_at` option is already `EXPIRED` and an exercise attempt fails step 4 with `ERR_INVALID_STATE` before ownership (step 6) or window (step 7) — `implementation/app.py:59-63` (`before_request` → `sweep_time_transitions`), `implementation/services.py:182-191`, exercise pipeline at `implementation/app.py:1094-1106`.
- §2.6 (Money, Precision, and Rounding) — insert — pinned that rate arithmetic is exact decimal arithmetic (no binary floating-point intermediate), so exact half-cent products round up and the §3.4 escalator ceiling admits the 0.15 boundary value — `implementation/helpers.py:55,102-104` (`parse_float=Decimal`, `_is_number` accepts Decimal), `implementation/app.py:623` (exact `Decimal("0.15")` bounds check), `implementation/services.py:13-19` (D/round_cents), serialization back to plain JSON numbers at `implementation/app.py:105-116`.

**Step-7 items with no PRD edit (with justification):**
- test_02 missing `create_draft_proposal` import — pure test-authoring bug; nothing in PRD implicated.
- test_03 `test_contract_aav_nested_rounding_order` expected-value correction — pure fixture arithmetic slip; PRD §3.4's formula uniquely yields `aav_cents == 11_125_002` (bases 10,000,000/10,750,000; bonus share 500,001; incentive share 250,001; cap hits 10,750,002/11,500,002; total 22,250,004; /2 = 11,125,002), matching `implementation/services.py:26-40` — no PRD silence.
- test_05 relaxation to `validate_error_is_one_of([ERR_OWNERSHIP_VIOLATION, ERR_INVALID_STATE])` — the underlying silence (when auto-expiry is evaluated relative to the pipeline) is pinned by the §2.5 edit above.

**Per-edit pre-edit search logs:**

*Edit 1 (§2.5)*: (a) Subject: evaluation point of automatic time-driven state transitions. (b) Enumerated paths: `app.py:59-69` (`_begin_request` sweeps before every route's pipeline, including reads and auth), `app.py:147-159` (set_clock sweeps post-set; response carries only `current_utc`, so no extra observable), `services.py:182-191` (endorsement `ACTIVE`→`COMPLETED` and tender `PENDING`→`EXPIRED` with `>=` thresholds, matching §3.7/§3.8 "reaches"), exercise pipeline `app.py:1088-1110` (state check before cert/ownership/window; ERR_WINDOW_CLOSED still reachable for not-yet-open windows, which wording does not disturb), endorsement terminate `app.py:1015-1027` (same sweep-first consequence via generic wording). (c) Wording kept generic ("a record whose transition instant the clock has passed is already observed in its new state") with the tender-exercise consequence stated as the specific case, avoiding any universal claim about endorsement termination while remaining consistent with it.

*Edit 2 (§2.6)*: (a) Subject: exactness of rates/percentages in parsing, calculations, and range checks. (b) Enumerated paths: `helpers.py:41-64,102-140` (parse_float=Decimal; number gates), `app.py:173` (fee_cap_pct intake, no bounds), `app.py:609,623-627` (escalator intake + exact bounds + valuation), `services.py:26-47` (valuation compounding; `escalator_projection` defined but never routed — not PRD-visible), `services.py:61-70` (endorsement tier/cap), `services.py:77-78` (signing fee, called `app.py:704`), `services.py:85-91` (transition split, called `app.py:405-415`), `app.py:1228-1235` (grievance UPHELD fee), `services.py:98-112` (split_pct stored as float literals 0.25/0.75/1.0 — exact in binary, never re-used arithmetically), `app.py:105-116` (`view()` Decimal→int/float output-only). (c) Scoped exactness to "rate arithmetic" (not internal representation) to stay consistent with float-literal split_pct storage; used "such as" for the escalator ceiling so no fee_cap_pct bound is implied (implementation enforces none); silent on response typing since view() emits standard JSON numbers already covered by §2.2.

## Step 9: Complete PRD — 2026-08-13T20:58:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1541_sports_agency_contract_cap_management/workspace/PRD_COMPLETED.md` produced from `PRD_FINALIZED.md` (PRD_FINALIZED existed, so it was the source).

**Source vs output:** PRD_FINALIZED.md 279 lines / 43,957 chars → PRD_COMPLETED.md 281 lines / 47,574 chars; char-delta **+3,565**. No sections added or removed; all edits are in-paragraph inserts/revisions (plus one appended sentence in §2.2).

**Counts:** 21 ambiguity-pins, 6 mismatch-revisions.

**Changes:**

- §2.2 — insert — ambiguity — unexpected server failures surface as `ERR_INTERNAL` (500) in the standard envelope — implementation/app.py:94-98
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) or negative `offset` → `ERR_INVALID_REQUEST` (400) — implementation/helpers.py:207-227
- §2.3 — insert — ambiguity — `created_at` sort ties keep insertion order — implementation/helpers.py:236-238
- §2.3 — insert — ambiguity — `has_more` = `offset + len(returned) < total_count` — implementation/response.py:54
- §2.4 — insert — ambiguity — `version` begins at 1; `created_at` == `updated_at` at creation; all server timestamps (`created_at`, `updated_at`, `certified_at`, `exercised_at`, `api_request_timestamp`) read the logical clock — implementation/helpers.py:177-183, implementation/response.py:30-31
- §2.7 — insert — ambiguity — undeclared path/method → `ERR_NOT_FOUND` (404); body must be a JSON object with exactly the declared fields else `ERR_INVALID_REQUEST`, checked after auth/role/path-resolution and before later semantic steps except `initiate_transition` (client-state check fires before body read); body-less endpoints ignore the body entirely — implementation/app.py:82-91, 371-375; implementation/helpers.py:41-70
- §2.7 — insert — ambiguity — body-referenced identifiers (`team_id`, `cap_season_id`, `primary_agent_id`, `target_agent_id`, `proposed_by_agent_id`, `filed_by_agent_id`) must resolve in scope else `ERR_NOT_FOUND` — implementation/app.py:324, 376, 611-612, 763, 1135
- §2.9 — insert — ambiguity — OCC comparison runs after path resolution and before the state check; missing/non-integer expected-version field → `ERR_INVALID_REQUEST` — implementation/app.py:680-683, 802-807, 840-843
- §3.1 — insert — ambiguity — no numeric range check on `fee_cap_pct` at agency creation (number type only) — implementation/app.py:171-173
- §3.1 — insert — ambiguity — duplicate agent email within agency → `ERR_INVALID_REQUEST` — implementation/app.py:207-209
- §3.1 — revise — mismatch — revocation moves only `ACTIVE` clients of the revoked agent into `TRANSITIONING` (clients already `TRANSITIONING`/`RELEASED` untouched), for both CERTIFIED and SUSPENDED revocations — implementation/app.py:300-306
- §3.2 — insert — ambiguity — client registration: named primary agent must resolve in agency (`ERR_NOT_FOUND`) and be `CERTIFIED` (`ERR_AGENT_NOT_CERTIFIED`) — implementation/app.py:324-326
- §3.2 — insert — ambiguity — initiate-transition target: unresolvable → `ERR_NOT_FOUND`, non-certified → `ERR_AGENT_NOT_CERTIFIED` — implementation/app.py:376-378
- §3.2 — insert — ambiguity — complete-transition with no recorded or no-longer-certified successor → `ERR_AGENT_NOT_CERTIFIED` — implementation/app.py:393-396
- §3.2 — insert — ambiguity — "current season year" in the transition-split rule is the logical clock's calendar year — implementation/app.py:402, services.py:85-86
- §3.3 — insert — ambiguity — `luxury_threshold_cents` ≤ `cap_limit_cents` → `ERR_INVALID_REQUEST` — implementation/app.py:488-489
- §3.3 — insert — ambiguity — closing a season with nonzero `reserved_cents` → `ERR_INVALID_STATE` — implementation/app.py:572-573
- §3.4 — revise — mismatch — dropped "and any later adjustment while the deal is still being negotiated" from the constraints sentence (no contract-adjustment endpoint exists) — implementation/app.py:590-646
- §3.4 — revise — mismatch — "recomputed whenever a valuation input changes" → valuation happens at creation only; money terms immutable thereafter — implementation/app.py (no update route), services.py:26-40
- §3.4 — revise — mismatch — deleted the sentence promising an on-demand per-season base projection (no such endpoint; `escalator_projection` is dead code) — implementation/services.py:43-47
- §3.5 — insert — ambiguity — drafting a proposal demands only that `proposed_by_agent_id` resolve in agency (`ERR_NOT_FOUND`); certification first demanded at submission — implementation/app.py:763
- §3.5 — insert — ambiguity — countering has no season-open, soft-cap, or concurrency gate (only SUBMITTED state), so a counter may raise the reservation above the luxury threshold — implementation/app.py:847-864
- §3.5 — insert — ambiguity — resubmission's soft-cap check is evaluated with the prior reservation still posted (prior + revised figures both counted) — implementation/app.py:818-828
- §3.5 — revise — mismatch — acceptance order reversed: PRD said "first demands season OPEN, then hard-cap"; impl (and §2.7 pipeline) run the hard-cap check first, then the season-OPEN lock check — implementation/app.py:884-891
- §3.7 — insert — ambiguity — window bounds are ISO 8601 datetime strings (unparseable → `ERR_INVALID_REQUEST`), close-not-after-open → `ERR_WINDOW_CLOSED`, bounds stored/echoed verbatim — implementation/app.py:1040-1058
- §3.7 — revise — mismatch — removed "locks the contract's `base_salary_cents` for the option year at the tender amount"; exercise mutates only the tender record — implementation/app.py:1088-1110
- §3.8 — insert — ambiguity — deal dates are ISO 8601 datetime strings echoed verbatim (unparseable → `ERR_INVALID_REQUEST`); `agent_fee_cents` is null until approval — implementation/app.py:942-964
- §3.8 — insert — ambiguity — approval: client not `ACTIVE` → `ERR_INVALID_STATE`; agency not `ACTIVE` → `ERR_RESOURCE_LOCKED` — implementation/app.py:998-1003
- §3.9 — insert — ambiguity — grievance filing: `filed_by_agent_id` must resolve in agency (`ERR_NOT_FOUND`); no certification or identity equivalence with the acting user demanded at filing — implementation/app.py:1124-1146
- §3.9 — insert — ambiguity — `resolution_outcome` is request-only (not persisted on the grievance); only the exact string `UPHELD` writes the fee ledger entry — implementation/app.py:1221-1236

Everything else in the implementation (endpoint set, role lists, state machines, all calculation formulas, rounding rules, cascade side effects, OCC field names, error catalogue, envelope shape) was already uniquely pinned by PRD_FINALIZED.md and verified against the code with no change needed.
