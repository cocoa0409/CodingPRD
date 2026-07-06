# Worklog — task_0705_podcast_production_editing

Scenario: Podcast Production & Editing Service: show onboarding & format, recording session & remote capture, edit/mix/master & turnaround, show-notes/transcript & publishing, distribution & hosting, sponsorship/ad-insertion coordination, per-episode vs retainer, asset/version delivery

Difficulty: Expert (scaffold-generator §0.4 Expert tier: 10–15 entities / 20–32 endpoints / 18–30 error codes / 3+ calculation variants / 4+ state machines) — applied to Step 2 scaffold generation only.

## Step 1: Create task directory — 2026-06-29T10:11:01.000Z

Task directory pre-created by caller at `tasks/task_0705_podcast_production_editing/` (with `workspace/` subdir). Step 1 index scan skipped per instructions to avoid ID contention during parallel runs. task_name = `task_0705_podcast_production_editing`.

## Step 3: Copy shared files — 2026-06-29T10:11:01.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes). (Done out of order while Step 2 scaffold subagent runs — Step 3 is independent of the scaffold.)

## Step 2 (finish): Generate two missing design indices — 2026-06-29T10:40:00.000Z

RESUME: `SCAFFOLD.yaml` (§1.1–§1.7) was already complete from the prior interrupted run; only the two design indices were missing. One blocking subagent generated ONLY the two missing files at EXPERT tier, cross-referenced to the existing `SCAFFOLD.yaml`, without modifying it. Orchestrator re-validated both on disk (valid YAML, correct single top-level keys) and confirmed `SCAFFOLD.yaml` byte-size unchanged (63537 bytes, mtime 10:21). Subagent's verbatim summary:

Everything verified. Both files are complete, valid, and lint-clean.

I generated the two missing EXPERT-tier design-index files for `task_0705_podcast_production_editing`, cross-referenced entirely against the existing `SCAFFOLD.yaml` (§1.1–§1.7). The main scaffold was treated as read-only and was not modified or opened for write.

**Files created:**
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1993 lines, single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1711 lines, single top-level key `scaffold_corner_design`

**Difficulty design (§1.8)** — all 9 rule_ids × 2 instances = **18 instances**:
- `dual_variant_calc` (2), `combinatorial_formula` (2), `non_linear_state_machine` (2), `transitive_cascade` (2), `priority_pair_validation_conflict` (2), `boundary_precision_check` (2), `cross_entity_state_dependency` (2), `resource_temporal_overlap` (2), `compensating_invariant` (2). Each instance grounds in real scaffold elements (e.g. `calculations.turnaround_due`, `state_machines.Episode.SCHEDULED_to_PUBLISHED`, `validations[priority=24]`, `concurrency_rules[campaign-reconcile-stale]`, real error_ids) and pins formula-derived asserts as literals computed by code — round-per-slot ad split (148 vs 147 sum-then-round), discount cap (subtotal 44000 → discount capped at 5000 → total 39000), late-fee SILVER boundary at lifetime snapshot 40000 (525 vs BRONZE 300), provisional vs final turnaround (2026-03-04 vs 2026-03-05), retainer projection-vs-close overage divergence (1 vs 0).

**Corner design (§1.9)** — **49 instances across 9 sections** (entities 10, state_machines 8, calculations 5, validations 6, endpoints 2, errors 9, rbac 3, cross_cutting 5, consistency_model 1): **37 non-stub** corner instances + **12 `excluded_because:` stubs**, every stub citing a real §1.8 instance by name. Sections/claim_types drawn verbatim from `references/claim-extraction-guide.md`.

**Verification:**
- `python3 scaffold_lint.py tasks/task_0705_podcast_production_editing` → **`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`** (619 calls scanned; 18 + 37 instances).
- Both files parse as valid YAML with exactly their required single top-level key; neither key appears inside `SCAFFOLD.yaml`.
- All instance `name:` values unique across both files; all `grounds:` and stub `difficulty_instance` references resolve.
- `SCAFFOLD.yaml` is untracked/unmodified; pre-existing `worklog.md` and `workspace/` left untouched.

Note: identity headers follow §1.7 (`ShowOwner` → `as_user_id` = owning Show.id; `ProducerEng` → `as_user_id` = Engineer.id); OCC `expected_*_version` payloads always reference a captured `${var}` (never a literal); bracketed JSONPath captures (`$.data[0].field`) are quoted to keep flow-mapping YAML valid.

## Step 4: Generate PRD — 2026-06-29T10:47:00.000Z

Blocking subagent generated `workspace/PRD.md` from `SCAFFOLD.yaml` only (both design indices withheld). Orchestrator confirmed PRD.md final on disk (47027 bytes, 322 lines, stable >100s; sections §1 Introduction / §2 Global Specs / §3 Business Logic & Workflows / §4 Endpoint Definitions / §5 Error Catalogue). Subagent's verbatim summary:

All verifications pass. The PRD is complete and on disk.

**Output path:** `workspace/PRD.md` (322 lines, 47 KB)
**Domain:** Podcast Production & Editing Service (EXPERT tier, workflow-orchestration + posture-driven gating).

**Major sections covered:**
- §1 Introduction (business problem, posture/dual-billing entanglement, logical clock note)
- §2 Global Specifications — 11 subsections: RBAC + identity translation, verbatim §2.2 envelope, pagination, common resource properties/versioning, production posture gate, editing-pipeline consistency, nested/filtered retrieval, validation rule ordering, billing ledger + lifetime snapshot, loudness conformance, OCC
- §3 Business Logic — 11 subsections by lifecycle/workflow: show onboarding & contracts, episode commissioning, recording/sessions/booking windows, deliverables & editing loop, scheduling/publishing/per-episode billing, turnaround deadlines, late-fee tiers, retainer waterfall reconciliation, invoice administration, sponsorship/revenue split, logical clock
- §4 Endpoint table (4 columns) and §5 Error catalogue (2 columns)

**Coverage counts described in prose:**
- Entities: 11 — Show, EngagementContract, RetainerCycle, Episode, Session, Engineer, Deliverable, AssetVersion, Invoice, AdCampaign, AdSlot (all 59 field names verbatim)
- Endpoints: 58 (matching the scaffold endpoint table exactly)
- Error codes: 24 (present in both §5 table and §2/§3 narrative)
- State machines: 7 entries — Show.production_posture (derived gate), EngagementContract, Episode (cyclic/branching revision loop), Session, AdCampaign, Invoice, RetainerCycle (all 54 enum/state values present)
- Calculations: 5 — turnaround_due (provisional/final), invoice_total, late_fee (tier-keyed on lifetime snapshot), retainer_reconciliation (waterfall, provisional/final), ad_revenue_split (per-slot rounding). Constants embedded in prose.

**Hard Contract Reports:** Contract 1 Field-Name Coverage 59/59 PASS; Contract 2 Rule Coverage (35 validations, 2 OCC rejections, all transitions across 7 machines, 5 calculations, sibling-branch symmetry) PASS; Contract 3 §3 Path Purity (355 backtick tokens scanned, 0 path/method tokens) PASS. §2.2 envelope verified byte-identical to canonical source. The two withheld design files were not opened; no sibling tasks accessed.

## Step 5: Generate Unit Tests — 2026-06-29T11:05:00.000Z

Launched concurrently with Step 6 (single message, two Agent calls) for physical isolation. Orchestrator confirmed on disk: 9 `test_helpers/` files + `test_suite/conftest.py` + 8 `test_*.py`; `pytest --collect-only` = 73 tests, zero collection errors. Subagent's verbatim summary:

All files import cleanly. Generation is complete.

I generated complete test infrastructure for `task_0705_podcast_production_editing` strictly from the two design indices (no freelance walking of SCAFFOLD.yaml).

**`test_helpers/` (Stage 1) — 9 files:** `types.py` (entity TypedDicts, all 11 entities carry `id/created_at/updated_at/version` per PRD §2.4 + status/role enums); `api_client.py` (`ApiClient(GenericApiClient)`, one method per endpoint); `api_errors.py` (`ApiErrorId` enum + HTTP status map); `assertions.py` (per-entity assertions + invoice-total and revenue-split invariant checkers); `factories.py` (payload factories, input fields only, PRD-exact names, required vs optional honored); `constants.py` (SLA hours, tier base prices, late-fee thresholds/rates, overage rates); `test_users.py` (opaque-role constants + per-instance builders: ShowOwner→Show.id, ProducerEng→Engineer.id); `fixtures.py` (composite setup driving INTAKE→PUBLISHED pipeline, retainer cycles, ad campaigns, REVIEW/EDITING staging, with correct identity threading); `__init__.py`.

**`test_suite/` — conftest + 8 domain-named files, 73 tests total:** Queue A (Difficulty) 36 tests — all 18 difficulty instances covered with ≥2 tests each; Queue B (Corner) 37 tests — all 37 non-stub corner instances covered with ≥1 test each.

**Verification:** every difficulty instance ≥2 tests, every non-stub corner ≥1 test; all 73 `Design:` tags resolve to real instances; all 12 corner stub `difficulty_instance` cross-references resolve. Every test has exactly one `Design:` line. All PRD citations verified verbatim (modulo markdown backticks/emphasis and whitespace). No skip/skipif/xfail; no scaffold-leakage terms. `pytest --collect-only` = 73 tests, zero import/collection errors.

**Instances skipped:** None failed the PRD-first filter — PRD covers every targeted rule with unique derivability. The 12 `excluded_because:` corner stubs were correctly NOT translated (their cited difficulty instances own the assertions); four initially mis-tagged tests were retagged to the difficulty instances they actually assert. Observation: PRD wraps identifiers in backticks and uses `*emphasis*`/`(§x.y)` inside rule sentences — citations match modulo those markers.

## Step 6: Generate Implementation — 2026-06-29T11:05:00.000Z

Launched concurrently with Step 5. Orchestrator confirmed on disk: 26 source files; `start.sh` reads `$PORT` (app.py default 10000), binds 0.0.0.0, foreground via `exec python3 app.py`, guarded pip-install; `requirements.txt` = flask==3.0.3. Subagent's verbatim summary:

Everything checks out. The audit confirms no seeding, no SQLite, no file persistence, no /tmp cache. Storage is purely in-memory dicts that start empty on every boot.

I generated a complete Python + Flask implementation for the Podcast Production & Editing API at `workspace/implementation/`.

**Files written (26 source files):** `start.sh` (launcher); `app.py` (Flask entry, blueprint registration, global error handlers); `requirements.txt` (flask==3.0.3); core infra `clock.py` (logical clock, default `2026-03-01T00:00:00Z`), `db.py` (in-memory store), `errors.py`, `response.py` (envelope), `middleware.py` (auth/RBAC/validation/pagination), `serialize.py`, `timeutil.py`, `constants.py`; `routes/` (10 modules: shows, contracts, retainer_cycles, engineers, episodes, sessions, deliverables, invoices, ad_campaigns, clock_routes + common helpers); `services/` (3 modules: `calc.py` turnaround/invoice/late-fee/ad-split, `retainer.py` waterfall reconciliation, `show_state.py` posture + open_episode_count recompute).

**start.sh contract — confirmed:** reads `$PORT` (default 10000 via app.py), binds 0.0.0.0, FOREGROUND via `exec python3 app.py` (no `&`); guards `pip install` on a cheap `import flask` check to avoid per-test-reboot contention.

**Storage model:** in-memory only — Python dicts keyed by UUID (`db.py`), wiped on every process start. No SQLite, no JSON dump, no /tmp, no external persistence. Audit confirmed no seeding/preloading; fresh-boot test verified empty collections + clock default.

**Endpoints implemented:** 58 routes (35 POST + 23 GET), matching PRD §4 exactly.

**Verification:** booted via `start.sh`, ran 72 functional assertions across three scripts — all passing. Coverage: full editing pipeline (INTAKE→PUBLISHED), posture gating/recompute (SUSPENDED/ON_HOLD/ACTIVE), provisional vs final turnaround, late-fee tiers with pre-invoice lifetime snapshot ordering, discount capping, per-slot ad-revenue rounding, retainer waterfall (projection non-persistence + close billing), both OCC guards (contract terminate / campaign reconcile, ERR_STALE_VERSION 412), STUDIO overlap + REMOTE buffer temporal checks, loudness conformance at both points, supersede validation, envelope/error format.

**One ambiguity noted:** `LOUDNESS_TOLERANCE_LUFS` is referenced by PRD ("a fixed tolerance") and scaffold but no numeric value is declared anywhere. Used `1.0 LU` (standard mastering conformance tolerance), documented in `constants.py`. If the test suite expects a different value, that single constant is the only place to adjust.

## Step 7: Test/fix loop — 2026-06-29T12:00:18.000Z

**Iterations:** 2 stability sweeps (baseline + 1 fix round), each run as 2 waves of 4 rounds (8-core host self-saturates under 8 concurrent rounds → per the parallel-SIGTERM/host-saturation memory). Baseline: 66/73 passing in all 8 rounds (7 deterministic failures, no flakiness, 0 host boot-timeout ERRORs). After fixes: **73/73 in all 8 rounds**.

**Failing tests (union across 8 rounds, all deterministic):**
1. `test_provisional_then_final_turnaround_diverge` (test_02)
2. `test_provisional_turnaround_standard_one_track` (test_02)
3. `test_session_complete_bubbles_episode_to_editing` (test_02)
4. `test_session_complete_sets_recording_ended_at` (test_02)
5. `test_lock_assets_freezes_track_count_and_stamps_complete` (test_08)
6. `test_overlapping_cycle_same_contract_rejected` (test_03)
7. `test_create_show_returns_computed_defaults` (test_08)

Root-caused into 3 clusters, resolved per the STEP 0→1→2→3 diagnostic protocol.

**Tests deleted:** NONE. (No PRD-silence or unique-derivability collapse found — every failure was a fixture/assertion mis-format or a missing test-side enum, all of which trace to verbatim PRD prose.)

**Fixes applied to `test_suite/` (STEP 2 — assertion mis-translates PRD format; cluster A, tests 1–5):**
- `test_02_turnaround_and_cascades.py` (7 assertion sites across 4 tests) and `test_08_crud_and_validation.py` (1 site): expected timestamp literals corrected from bare `...:00Z` to PRD's three-fractional-digit form `...:00.000Z`. PRD §2.4 ("`created_at` … ISO 8601 UTC timestamp with three fractional digits") and §2.2 (`api_request_timestamp` "with three fractional digits") fix the system-wide emission convention; the implementation's single `format_iso8601` correctly normalises every stamped timestamp (turnaround_due_utc, recording_ended_at, completed_at, assets_complete_at) to `.000Z`. The tests' literals had dropped the fractional digits. Fix keeps exact-string equality (NOT a weakening) and makes the assertion faithful to the PRD format. The asserted calculation/cascade *values* (dates) were already correct and unchanged.

**Fixes applied to `test_helpers/` (STEP 2 — fixture omits a PRD-declared error id; cluster B, test 6):**
- `api_errors.py`: added `ERR_CYCLE_OVERLAP = "ERR_CYCLE_OVERLAP"` to the `ApiErrorId` enum and `ERR_CYCLE_OVERLAP: 409` to `HTTP_STATUS_CODES`. PRD §3.7 names it verbatim ("any true overlap is rejected with `ERR_CYCLE_OVERLAP`"); the implementation already raises it with HTTP 409 (sibling `ERR_SESSION_OVERLAP` is likewise 409). The test (`test_overlapping_cycle_same_contract_rejected`) referenced `ApiErrorId.ERR_CYCLE_OVERLAP`, which the generated enum had simply omitted (AttributeError). Pure test-side omission of a PRD-covered error.

**Fixes applied to `implementation/` (STEP 3 — PRD covers + uniquely determines; cluster C, test 7):**
- `db.py` `Store.create`: changed entity id minting from `uuid.uuid4().hex` (32-char dashless) to `str(uuid.uuid4())` (canonical hyphenated RFC 4122). PRD §2.4 says "The `id` is a server-minted UUID with no type prefix." The canonical textual representation of a UUID is hyphenated, and the benchmark's shared `is_valid_uuid` validator (the project-wide notion of a valid UUID, used by `assertions._assert_common`) requires the canonical 8-4-4-4-12 form. The dashless `.hex` rendering is the non-standard one; `str(uuid.uuid4())` is the natural PRD-faithful choice. Ids are used only as opaque dict keys / FK strings / X-User-ID values, so the representation change is behaviourally safe across the codebase. Fixed `test_create_show_returns_computed_defaults` (the only test that invokes `assert_show` → `_assert_common` → `is_valid_uuid`).

**Final sweep:** 73/73 × 8 rounds, 0 failures, 0 errors, 0 skipped. results.1.json–results.8.json on disk as durable evidence.

## Step 8: Finalize PRD (PRD_FINALIZED.md) — 2026-06-29T12:06:50.000Z

Ran (not skipped — Step 7 made implementation + test_helpers + test_suite fixes). Fresh subagent produced `workspace/PRD_FINALIZED.md` as a minimal patch of `PRD.md` aligned to `implementation/`, scoped to the Step-7 diff, with the NO-NEW-MISMATCH global enumeration applied per the skill. Orchestrator-verified final on disk: PRD.md 322 → PRD_FINALIZED.md 325 lines (+3). Subagent's verbatim summary:

All edits applied. Here is the exit summary.

## Summary

**Line counts:** PRD.md = 322 lines; PRD_FINALIZED.md = 325 lines; delta = +3 lines (+0.93%).

**Changes (one bullet each):**

- **§2.4 — revise — UUID id representation pinned to canonical hyphenated RFC 4122 form (not dashless hex)** — `implementation/db.py:30` (`rid = str(uuid.uuid4())`).
- **§2.4 — insert — added a universal rule that every emitted timestamp (common `created_at`/`updated_at` *and* all domain timestamp fields + window fields) is formatted as ISO 8601 UTC with exactly three fractional digits + trailing `Z`; also added "with three fractional digits" to the `updated_at` sentence for parallelism** — `implementation/timeutil.py:31` + `implementation/serialize.py:9-33`.
- **§5 — insert — added `ERR_CYCLE_OVERLAP | 409 Conflict` row to the Error Code Catalogue** — `implementation/errors.py:31` (`ERR_CYCLE_OVERLAP = ("ERR_CYCLE_OVERLAP", 409)`).

**Per-edit pre-edit search log:**

1. **UUID id representation**
   - (a) Subject: how entity `id` is minted/represented.
   - (b) Paths enumerated/read: `db.py` `Store.create` (the *only* id minter — `str(uuid.uuid4())`); confirmed all 11 entity collections route through `Store.create`; checked `response.py:_request_id` (`req_` + random alnum) — that's `api_request_id`, a *separate* field already governed by §2.2, not an entity `id`.
   - (c) Adjustment: scoped wording to the resource `id` sentence (which §2.4 already isolates) so it cannot be read as covering `api_request_id`. No further change needed.

2. **Timestamp three-fractional-digit format**
   - (a) Subject: fractional-digit format of every timestamp the system emits.
   - (b) Paths enumerated/read: `serialize.py` `_DATETIME_FIELDS` (13 fields) + `format_iso8601`; `timeutil.py:format_iso8601` (always `microsecond//1000:03d` + `Z`); `response.py:_meta` (identical inline format for `api_request_timestamp`); grepped every route — *all* responses go through `serialize`/`serialize_list`, no direct timestamp emission; confirmed window inputs (`scheduled_*`, `cycle_*`) are parsed via `parse_iso8601` into datetimes (`sessions.py:41-42`, `retainer_cycles.py:33-34`) and re-emitted normalized; confirmed stamped fields (`completed_at`, `recording_ended_at`, `turnaround_due_utc`, `assets_complete_at`, `published_at`, `activated_at`, `closed_at`) all stored as datetimes from `clock.now()`/calc and emitted via the same path.
   - (c) Adjustment: used a *universal* claim ("every timestamp value the system emits ... uniformly") with "for example" markers rather than an exhaustive field list, so no field is implicitly excluded (NO-NEW-MISMATCH); explicitly noted "normalized ... on output regardless of the precision in which they were supplied" to keep client-supplied window fields consistent.

3. **ERR_CYCLE_OVERLAP catalogue row**
   - (a) Subject: HTTP status mapping for ERR_CYCLE_OVERLAP.
   - (b) Paths enumerated/read: `errors.py:31` (single mapping → 409); `routes/retainer_cycles.py:45` (single raise site); confirmed PRD §3.8 prose already names the error + trigger condition verbatim, and PRD prose never carries HTTP statuses (only §5 does); §5 catalogue had no row for it.
   - (c) Adjustment: none to wording (one true table row). Note: step_7_diff classified this as a pure test-helper fixture omission; however the §5 catalogue (the PRD's sole authoritative Error-ID→status source) genuinely omits the HTTP status, which the implementation pins to 409. Pinning it satisfies the "patch only when impl pinned a choice PRD left open" rule and makes PRD_FINALIZED self-sufficient for behavioral equivalence. This was a deliberate judgment call against the step-7 heuristic steer, made because the omission is a literal, demonstrable silence with zero mismatch risk.

(Orchestrator note: ERR_CYCLE_OVERLAP appears in the §5 catalogue table as a 409 row; the §3 retainer-cycle prose already named the error verbatim, so only the catalogue HTTP-status row was added.)

## Step 9: Complete PRD (PRD_COMPLETED.md) — 2026-06-29T12:22:00.000Z

Always-run full impl-vs-PRD scan. Fresh subagent produced `workspace/PRD_COMPLETED.md` from `PRD_FINALIZED.md`. Orchestrator-verified final on disk: 329 lines; §2.4 UUID/three-fractional-digit pins and §5 ERR_CYCLE_OVERLAP row preserved; no impl/test source changed after the green sweep (results.1–8.json remain valid). Subagent's verbatim summary:

## Summary

**Files:** `/home/ubuntu/github/CodingPRD/tasks/task_0705_podcast_production_editing/workspace/PRD_COMPLETED.md` produced by `cp` from `PRD_FINALIZED.md`, then edited in place.

- **Line counts:** PRD_FINALIZED.md = 325 lines → PRD_COMPLETED.md = 329 lines (+4 lines)
- **Char delta:** 47,947 → 50,768 chars (+2,821)
- **Counts:** 16 ambiguity-pins, 5 mismatch-revisions (21 logical pins across 18 diff hunks / 12 sections)
- The finalized §2.4 UUID + three-fractional-digit timestamp pins and the §5 catalogue were left intact (the only §2.4 edit was "begins at its initial value" → "begins at 1").

### Per-change bullets

- §2.1 — insert — mismatch — asset-version read/accept/reject are NOT subject to the ShowOwner ownership check (and clarified the check does cover the show itself and its contracts) — routes/deliverables.py:121,129,156 (no ownership guard anywhere)
- §2.2 — insert — ambiguity — api_request_timestamp is server wall-clock time, independent of the logical clock — response.py:21-27
- §2.3 — insert — ambiguity — a non-integer limit/offset is rejected with ERR_INVALID_PAGINATION — middleware.py:149-162
- §2.3 — insert — ambiguity — equal creation timestamps are ordered by insertion sequence (common under the logical clock) — middleware.py:168, db.py:36
- §2.3 — insert — ambiguity — total_count is post-filter match count; has_more is offset+limit < total_count — middleware.py:170-176
- §2.4 — revise — ambiguity — version begins at 1 — db.py:36
- §2.7 — insert — ambiguity — deliverables list also filterable by kind — routes/deliverables.py:44-45
- §2.7 — insert — ambiguity — ShowOwner list scoping: contracts/episodes/deliverables/invoices/retainer-cycles are narrowed to the caller's show; shows & asset-versions are not — routes/contracts.py:60, episodes.py:104, deliverables.py:48, invoices.py:34, retainer_cycles.py:70 (vs shows.py:44, deliverables.py:102 unscoped)
- §2.8 — insert — ambiguity — out-of-range/bound numeric field values are rejected with ERR_INVALID_REQUEST — shows.py:30, contracts.py:29-34, episodes.py:60,126, engineers.py:22, ad_campaigns.py:26,134
- §2.10 — insert — ambiguity — loudness tolerance is fixed at 1.0 LU — constants.py:24
- §2.10 — insert — ambiguity — a MASTER_AUDIO version with null measured loudness skips the conformance check — routes/deliverables.py:142, episodes.py:175
- §2.10 — revise — mismatch — both loudness enforcement points are in §3.4 (was "§3.4 and §3.5"; §3.5 has no loudness check) — episodes.py:175 (approve), deliverables.py:139 (accept)
- §2.11 — insert — ambiguity — expected_*_version is validated inside the concurrency step after transition-legality (wrong-state => ERR_INVALID_STATE even when the field is absent) — contracts.py:102-112, ad_campaigns.py:85-95
- §3.1 — revise — mismatch — retainer monthly_included_episodes is not required to be >0 at creation (only >=0, and =0 for per-episode); positivity enforced only at activation — contracts.py:29-33 (create has no RETAINER>0 check), :82-84
- §3.1 — insert — ambiguity — activation with monthly_included_episodes < 1 fails with ERR_INVALID_REQUEST — contracts.py:82-84
- §3.3 — revise — mismatch — engineer-active is checked LAST, after window/show/capacity (overlap & buffer) — sessions.py:46-78 (active check at 76-78)
- §3.4 — insert — mismatch — deliverable creation is not gated on episode pipeline state (despite "while an episode is in editing") — routes/deliverables.py:16-30
- §3.4 — insert — ambiguity — lock-assets requires raw_track_count >= 1 and has no episode-state precondition — episodes.py:119-131
- §3.8 — insert — ambiguity — a RETAINER_OVERAGE invoice is never treated as late-delivered, so late_fee_cents is always 0 — retainer_cycles.py:129-130, services/calc.py:77-91
- §3.10 — insert — ambiguity — campaign show_payout_cents/platform_take_cents are 0 until reconciliation — ad_campaigns.py:32-33
- §3.10 — insert — ambiguity — adding a slot to a non-DRAFT campaign is rejected with ERR_INVALID_STATE — ad_campaigns.py:137-138

### Notes on items deliberately left unchanged
- The §2.8 generic ordering (ownership before existence) was left as-is: for path/chained resources the impl necessarily fetches a resource (existence) before it can compare its show/engineer linkage (ownership), so the stated precedence only differs in indeterminate cases that resolve to the same 404.
- Response field shapes for all 11 entities matched the PRD; calculation formulas (per-episode invoice, late-fee tiers/rates, retainer waterfall, ad revenue split, turnaround SLA), the round-half-up convention, snapshot ordering (§2.9), posture recompute order, and the logical-clock default were already uniquely pinned and required no change.

## Step 7→9 EXIT — 2026-06-29T12:22:00.000Z

Final 2×4 stability sweep (post-Step-7-fixes, unchanged by Steps 8–9 which edited only PRD docs): all 8 rounds 73/73 passed, 0 failed, 0 errors, 0 skipped. results.1.json–results.8.json on disk as durable evidence. PRD_COMPLETED.md (329 lines) present. Tail complete.
