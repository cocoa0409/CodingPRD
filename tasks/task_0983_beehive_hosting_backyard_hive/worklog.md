# Worklog — task_0983_beehive_hosting_backyard_hive

## Step 1: Create task directory — 2026-08-10T00:00:00.000Z

Pre-assigned output folder `tasks/task_0983_beehive_hosting_backyard_hive` with `workspace/` subdirectory already created by the headless launcher. Step 1 auto-index scan skipped per instructions; directory verified present on disk.

## Step 2: Generate scaffold — 2026-08-10T10:37:00.000Z

Scaffold generation complete. All three artifacts are written and lint-clean.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    75
  §1.1 entities declared:     15
  §1.8 instances scanned:     26
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  792

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_0983_beehive_hosting_backyard_hive/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_0983_beehive_hosting_backyard_hive/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:`, 26 instances
- `/home/ubuntu/github/CodingPRD/tasks/task_0983_beehive_hosting_backyard_hive/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:`, 58 instances (51 active + 7 excluded_because stubs)

## Design summary (harder-than-expert)

- **Profile**: primary archetype posture-driven gating (hive posture derived from mite-load thresholds gates harvest/split/capture), secondary quota/allocation (season honey pool split). Layers: optimistic concurrency, cascading side effects, rate/threshold triggers, scheduled actions. Flat topology, `segregation_of_duties` role model (recorder != verifier/approver), immediate consistency.
- **Surface**: 15 entities, 75 endpoints, 36 error codes, 10 calculations (3 dual-variant), 15 state machines, 11 validation priority tiers, 5 roles (Host entity-backed; Anonymous/Beekeeper/ApiaryManager/PlatformOps opaque), 2 OCC concurrency rules (Agreement amendment, Subscription change-plan).
- **Nine difficulty rules, all ≥2 instances with distinct differentiators**: dual-variant calcs on 3 domains (honey allocation, overwinter billing credit, hive posture); combinatorial formulas in all 3 modes (nested-min cap / per-harvest-then-sum rounding / pinned circular evaluation order); 3 cyclic state machines (Agreement amendment loop, Inspection revision loop, Subscription cure cycle); cascades of depth 3 from two triggers (verify→hive→harvest→allocation; rollover→invoice→subscription→host); 3 distinct validation-priority pairs; 4 boundary checks on distinct metrics/endpoints (3.00 mites/100 inclusive, capacity ==, 18.6% moisture strict->, 24h cooling-off inclusive); 3 cross-entity state dependencies (Harvest→Agreement, RemovalJob→Incident, Hive→Site); 3 temporal-overlap semantics (half-open treatments, 2h crew buffer, closed-interval agreement terms); 2 compensating invariants over different conserved quantities (honey kg mass, balance cents).
- **Verification beyond lint**: all pinned arithmetic literals re-executed with Decimal math (e.g., projected 7.866 vs final 6.141 kg on identical harvest data; per-harvest rounding 0.202 vs sum-then-round 0.201; late-fee compounding 6268); grounds resolvability, cross-file name uniqueness, enum closure, error triggerability (all 36 errors exercised), forbidden-vocabulary scan, and call-by-call replay against §1.2/§1.4/§1.6 all pass. Logical-clock endpoint `POST /api/_clock/set_current_utc` pins the mandatory `2026-05-01T00:00:00Z` startup default.

## Step 3: Copy shared files — 2026-08-10T10:40:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_0983_beehive_hosting_backyard_hive/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T10:46:00.000Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_0983_beehive_hosting_backyard_hive/workspace/PRD.md`.

## What was done

Generated a prose-style PRD from the scaffold, structured as:
- **§1 Introduction** — 2 paragraphs (host pain-point angle + system scope).
- **§2 Global Specifications** — 12 subsections with domain-derived titles: RBAC & identity resolution (2.1), the verbatim response-structure contract (2.2, byte-identical to `section-2.2-response-structure.md`), pagination (2.3), common resource properties (2.4), the logical clock and lazy expiry (2.5), season rollover sweep (2.6), authoritative vs. provisional posture variants (2.7), site capacity/occupancy (2.8), OCC (2.9), segregation of duties (2.10), decimal precision (2.11), and the full 11-step validation pipeline with error IDs (2.12).
- **§3 Business Logic** — 9 subsections organized by domain workflow (onboarding/waivers/sites/incidents; agreements; hive placement; inspections/posture/quarantine; treatments/withdrawal/harvests; allocation/settlement; swarms; removals; subscriptions/billing/education/standing). All ten calculations rendered as precise prose (mite-load rounding, posture ladder with 2.00/3.00/9.00 thresholds, moisture penalty with the 18.6 boundary, per-harvest share rounding pinned before summation, the six-step reserve waterfall with the 100 kg tier, compounding 3%-per-week late fees with per-line rounding, the 4000-cent overwinter credit in both variants, capacity bonuses, reputation decay, cooling-off fee). No HTTP methods or paths in §3 backticks.
- **§4** — 75 endpoint rows, 4 columns only (Method, Path, Description, Authorized Role).
- **§5** — 36 error rows, 2 columns only (Error ID, HTTP Status).

The forbidden difficulty/corner design files were not opened.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoint inputs + query/path params: 110 required, 110 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in ordered prose (§2.12), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (propose-amendment + change-plan, expected_*_version + ERR_STALE_VERSION/412 named), 0 missing
- state_machines[].transitions: 41 checked, 41 fully expressed (preconditions + error IDs + side effects), 0 missing
- calculations[]: 10 checked, 10 fully expressed in precise prose, 0 missing
- validations[] conditions: all matchable to error_id in §2.12/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: defaults/initials/constraints reconstructible from prose, 0 missing
- sibling-branch symmetry: accept/reject, pay OPEN/OVERDUE, 3 incident outcomes, dispatch/capture/mark-lost — equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 510
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verification: §2.2 matches the fixed block byte-for-byte (including `req_RANDOMALPHANUM123456` and the empty `"data": { }`); §4 table has exactly 75 endpoint rows; §5 has exactly 36 error rows; every `errors[].id` from the scaffold appears in §2/§3 prose.

## Step 5: Generate unit tests — 2026-08-10T11:15:00.000Z

All checks pass. The suite is complete.

## Report

**Generated under** `/home/ubuntu/github/CodingPRD/tasks/task_0983_beehive_hosting_backyard_hive/`:

**`test_helpers/` (Stage 1)** — 9 modules:
- `types.py` — 15 entity TypedDicts + status/role enums (all entities carry `id`/`created_at`/`updated_at`/`version` per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (all 75); headers optional so the missing-header test can send none
- `api_errors.py` — full `ApiErrorId` enum + §5 HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserts + `assert_allocation_conservation` (§3.6 identity)
- `factories.py`, `constants.py` (all PRD thresholds: 2.00/3.00/9.00 mite ladder, 18.6% moisture, 6000 bps cap, 3%/6% reserve, 4000c overwinter, 24h cooling-off, 48h notice, 2h crew buffer, 72h swarm expiry, 365d waiver, 30d freshness)
- `test_users.py` — `TEST_USERS` for opaque roles + `make_host_headers(host.id)` for the entity-backed Host role
- `fixtures.py` — composite tiers: active host → site → signed agreement → hive, verified-inspection chains, completed treatments, paid subscriptions, course completion, full allocation scenarios (parameterized plan/education/bps/harvest schedule), rollover helpers, swarm/removal shortcuts
- `__init__.py` — barrel export (framework + PRD-specific)

**`test_suite/` (Stage 2)** — `conftest.py` + 10 concern-grouped files, **102 tests**: hosts/envelope (7), agreements (8), hives/capacity/swarms (10), inspections/posture (11), treatments/harvests (13), allocations (11), removals (13), billing (16), education/reputation (5), security/RBAC (8).

**Coverage audit (programmatic, against the two yamls):** 76 of 77 non-stub instances covered — all 51 non-stub corner instances ≥1 test, all difficulty instances ≥2 tests except one skip (below). Every test docstring carries a verbatim PRD citation and ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line copied from the source `name:`; all 158 quoted spans grep-verified verbatim against `PRD.md`. No skip/xfail markers; no scaffold references; pytest collects all 102 tests cleanly.

**Skipped instance (PRD-first filter, no placeholder emitted):**
- `Difficulty/cross_entity_state_dependency/harvest_blocked_when_agreement_expired` — fails unique derivability. PRD §2.12 step 10 scopes the agreement-term gate to "swarm captures and hive installs" only, and §3.5's harvest-recording requirements (operable hive, inspection freshness, non-quarantine, withdrawal embargo) name no agreement-state check. A faithful PRD-only implementer could create the harvest successfully, so the asserted `ERR_AGREEMENT_NOT_ACTIVE` rejection is not derivable from the contract.

**Partial-assertion note:** `Corner/endpoints/hive_split_requires_strong_posture` — the WATCH-parent rejection claim is not PRD-derivable (§3.3 enumerates split gates as site CLEAR, capacity, parent operable and non-quarantined; it never conditions on WATCH). The emitted test asserts only the PRD-pinned portion: successful split creates a child with `parent_hive_id`, lifecycle `ACTIVE`, posture `STABLE`, discoverable via the `parent_hive_id` list filter.

## Step 6: Generate implementation — 2026-08-10T11:15:00.000Z

Implementation complete. The Beehive Hosting API is fully implemented in Python + Flask at `/home/ubuntu/github/CodingPRD/tasks/task_0983_beehive_hosting_backyard_hive/workspace/implementation/`.

## Deliverables

- **`start.sh`** — executable launcher; guarded pip install (`if ! python3 -c "import flask"` so per-test reboots skip reinstall), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000). Verified: boots and answers HTTP in ~2s, reboots cleanly with empty state and default clock `2026-05-01T00:00:00Z`.
- **`app.py`** — Flask entry, global request lock (atomicity for cascades), error handlers.
- **`db.py`** — in-memory store (empty at boot, no seeding), logical clock, sequence counter.
- **`errors.py`** — full error catalog with exact IDs/HTTP statuses from the scaffold (catalog wins over the validation-table's category-level statuses, e.g. `ERR_SITE_BLOCKED`=400, `ERR_REMOVAL_NOT_ACTIONABLE`=400).
- **`util.py`** — tolerant ISO-8601 parsing (bare dates → midnight UTC), 3-fractional-digit `...Z` serialization, `ROUND_HALF_UP` Decimal helpers, request-shape validators.
- **`response.py`** — exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination meta `limit/offset/total_count/has_more` (default 10, clamp 1–100).
- **`middleware.py`** — header auth (`X-User-ID`/`X-User-Role`, 5 roles), body parsing with `parse_float=Decimal` to preserve exact decimal inputs.
- **`services.py`** — posture ladder (authoritative VERIFIED-only vs provisional VERIFIED+SUBMITTED), mite load (2dp), net harvest (moisture > 18.6 strictly penalized, 3dp), per-harvest-rounded host share (cap 6000 bps), pinned waterfall (pool → host → edu_bonus → reserve 3%/6% at 100kg → operator remainder, exact conservation), invoice math (per-line rounded late fees at 3%/full-week compounding on unpaid totals, floor-0 totals, due = issued + 7d), overwinter credit (projected live vs realized at close), effective capacity (PREMIUM/ADV-201 bonuses), lazy expiry (agreements, swarms), quarantine cascades, cure cascades, and the full atomic rollover sweep (close/open season, allocation finalization with close-pinned inputs, agreement/swarm sweeps, pending-plan application before invoice issuance, invoice aging, ACTIVE→PAST_DUE→SUSPENDED standing, host→LIMITED, stand-alone cancellation-fee adjustment invoices riding carried balance).
- **`routes_core.py` / `routes_agreements.py` / `routes_field.py` / `routes_ops.py`** — all 75 endpoints with the §2.12 validation pipeline order (headers → role → ownership → existence → shape → state/OCC → safety → business → referential → temporal → fiscal).

## Verification

Four self-written suites (~120 assertions) run against fresh `start.sh` boots, all green: core flows (auth errors, OCC 412s, amendment cycle, capacity boundary inclusive-reject, SoD, rollover invoice math with late fees and credit floor, distribution), edge cases (quarantine cascade voiding RECORDED harvests, provisional-vs-authoritative divergence, half-open treatment windows, withdrawal embargo exclusivity at `withdrawal_end_date`, swarm 72h lazy expiry, crew 2h buffer with exact-2h allowed, 48h notice boundary, 24h cooling-off boundary, incident site-blocking at SEVERE/3-REPORTED, reputation penalties, lazy agreement expiry, 365-day waiver lapse/renewal, pagination meta), deep billing (PAST_DUE→SUSPENDED across consecutive rollovers, adjustment invoices, payment cure cascades), and threshold boundaries (mite 2.00/3.00/9.00, per-harvest round-then-sum).

All test-side failures encountered during verification were artifacts of my own test scripts (unadvanced clock, unpaid-invoice preconditions, stale season IDs), not implementation bugs.

## Step 7 (attempt 1): Fix loop — 2026-08-10T11:30:00.000Z

First fix subagent completed the initial 8-round sweep (88–90/102 passing per round; stable union of ~12–14 failing tests, e.g. `test_host_missing_email_rejected`, `test_host_creation_defaults_and_system_fields`, `test_site_creation_default_capacity_applied`, agreement proposal-cycle tests) and began diagnosis (was analyzing a `withdrawal_end_date` ISO-format question) but the subagent terminated mid-diagnosis without emitting the final Summary block. Results files from the sweep persist on disk. Respawning a fresh fix subagent to continue the loop from the existing results.

## Step 7 (attempt 2, final): Fix loop — 2026-08-10T11:45:00.000Z

## Summary

- **Iterations run:** 2 sweeps (initial diagnostic + post-fix verification).

- **Tests deleted:** None.

- **Tests modified (STEP 1c — partial coverage, removed uncovered assertion):**
  - `test_04_inspections_posture.py::TestInspectionReviewLoop::test_resubmit_then_verify_completes_loop` — removed the exact-string equality on `last_verified_inspection_at`. PRD §2.4 pins three-fractional-digit format only for `api_request_timestamp`, `created_at`, and `updated_at`; the format of this derived field is unspecified, so `"…Z"` and `"….000Z"` are both PRD-consistent (DEFAULT-VALUE SILENCE on derived-datetime output format).
  - `test_05_treatments_harvests.py::TestTreatmentWindows::test_adjacent_windows_allowed` — replaced exact-string `withdrawal_end_date` equality with instant comparison via `datetime.fromisoformat`. Same DEFAULT-VALUE SILENCE pattern; kept the substantive assertion (end_date + 14 days).

- **Fixes applied to `test_helpers/`:**
  - `test_helpers/fixtures.py::setup_allocation_scenario` — added per-harvest `collected_on` override via the `inspection_schedule` entries (popped before forwarding to `create_and_verify_inspection`). Prior code forced harvests onto `2026-06-15/16` regardless of `inspected_at` overrides, making any future-dated inspection schedule trip `ERR_INSPECTION_STALE` (PRD §3.3 freshness rule) during setup.

- **Fixes applied to `test_suite/`:**
  - `test_06_allocations.py::_dual_variant_scenario` and `TestReservePinnedEvaluationOrder._reserve_scenario` — added explicit `collected_on` (`2026-07-05`, `2026-08-05`) paired with the existing `inspected_at` overrides so each harvest falls within the 30-day post-inspection freshness window required by PRD §3.3.

- **Fixes applied to `implementation/`:**
  - `workspace/implementation/routes_field.py::create_harvest` — after recording a harvest, if an allocation for the current OPEN season + this hive already exists in `PROJECTED` status, recompute the projected variant. PRD §3.6 defines `projected_pool_net_kg` as "the sum of `net_kg` over the pair's harvests in `RECORDED` or `APPROVED` status" — without this hook the field fell out of sync with its own definition whenever a RECORD followed the first APPROVE (observed in `test_allocation_recomputed_by_the_void`). The PRD's listed recompute triggers (approval/void/cascade) are non-exhaustive; the field's defining invariant is what forces the recompute.

**Final result: 8/8 rounds at 102/102 passed.**

## Step 8: Finalize PRD — 2026-08-10T11:51:00.000Z

Step 8 complete. `/home/ubuntu/github/CodingPRD/tasks/task_0983_beehive_hosting_backyard_hive/workspace/PRD_FINALIZED.md` written (copy of PRD.md + 3 inline edits, no new sections).

**Size delta:** PRD.md 348 lines / 53,145 chars → PRD_FINALIZED.md 350 lines / 53,911 chars; +0.57% lines, +1.44% chars.

**Changes (one bullet each):**
- §2.4 — insert — new paragraph after the `version` bullet pinning uniform timestamp rendering: every non-null date/time field returned (requester-supplied like `inspected_at`/`collected_on`, system stamps like `opened_at`/`due_at`, derived like `last_verified_inspection_at`/`withdrawal_end_date`) is ISO 8601 UTC with three fractional digits; bare calendar dates render at midnight UTC — impl: `util.py:30-35` (`iso()`, sole serializer), `util.py:43-58` (`pub`/`to_jsonable` on every entity), `response.py:18`, `services.py:252`, `routes_field.py:150`.
- §3.6 — revise — recompute-trigger sentence extended: "…every quarantine cascade that voids recorded harvests, **and every harvest recording once the pair's allocation exists**." — impl: `routes_field.py:260-263` (Step 7 fix in `create_harvest`).
- §3.5 — revise — harvest-recording paragraph extended: "Recording a harvest never creates an allocation, but when the allocation for the currently `OPEN` season and this hive already exists in `PROJECTED` status, recording recomputes its projected variant to include the new harvest (§3.6)." — impl: `routes_field.py:217-264`.

**Step-7 items requiring no edit:** the `test_helpers/fixtures.py` `collected_on` override and the `test_06_allocations.py` `collected_on` additions are pure fixture bugs — the 30-day post-inspection harvest-freshness window is already pinned in PRD §2.12 step 10 and §3.5, so prose was kept verbatim.

**Per-edit pre-edit search log:**

1. **Edit A (§2.4 timestamp rendering)**
   - (a) Subject: output format of date/datetime fields, specifically derived `last_verified_inspection_at` and `withdrawal_end_date`.
   - (b) Enumerated: `util.py:13-27` (`parse_dt` — bare date → midnight UTC, offsets normalized to UTC), `util.py:30-35` (`iso` — UTC + 3 fractional digits), `util.py:43-58` (`to_jsonable`/`pub` — applied to every entity response), `response.py:15-19` (meta timestamp via `iso`), and every datetime-bearing field across `routes_core.py` (`frost_date`, `opened_at`, `waiver_signed_at`), `routes_agreements.py` (`term_start/end_date`, `signed_at`, `installed_at`, `last_verified_inspection_at`), `routes_field.py` (`inspected_at`, `start/end_date`, `withdrawal_end_date`, `started_at`, `completed_at`, `collected_on`, `finalized_at`, `distributed_at`), `routes_ops.py` (`reported_at`, `requested_at`, `scheduled_start`, `completed_at`, `activated_at`, `paid_at`, `occurred_at`, `resolved_at`), `services.py` (`due_at`, invoice stamps). `grep` confirmed no other `strftime`/format path exists; clock endpoint returns empty data; `period_label` is a string label, not a datetime.
   - (c) Adjustments: added the "non-null" qualifier because `iso(None)` renders JSON null for unset fields (e.g. `signed_at` pre-signing); added the "bare calendar date renders at midnight UTC" clause to cover date-only inputs (`parse_dt` appends `T00:00:00Z`), which is precisely the `withdrawal_end_date` case Step 7 hit.

2. **Edit B (§3.6 recompute triggers)**
   - (a) Subject: HoneyAllocation projected-variant recompute triggers.
   - (b) Enumerated all four `recompute_allocation_projected` callsites: `routes_field.py:263` (create_harvest — only when an allocation for the record-time OPEN season exists and is PROJECTED), `:314` (approve_harvest — create-if-missing then recompute), `:330` (void_harvest — allocation guaranteed PROJECTED by the FINALIZED/DISTRIBUTED rejection at `:325-326`), `services.py:262` (quarantine cascade — PROJECTED allocations only). Also checked `finalize_allocation` (`services.py:210-242`, rollover-only final variant — distinct) and `distribute_allocation` (`routes_field.py:358-379`, APPROVED→SETTLED, no projected recompute — correct since allocation is then DISTRIBUTED); no other harvest-status mutation exists that could desync the projected sums.
   - (c) Adjustment: added the "once the pair's allocation exists" qualifier because recording never creates an allocation (creation is pinned to first approval in §3.6's first sentence, matching `approve_harvest`).

3. **Edit C (§3.5 recording side effect)**
   - (a) Subject: `create_harvest` side effect on an existing PROJECTED allocation.
   - (b) Enumerated the same four callsites as Edit B plus §3.5's existing approval/void sentences (verified they already match `routes_field.py:304-314` and `:329-330`).
   - (c) Adjustment: scoped wording to "currently `OPEN` season and this hive … in `PROJECTED` status" to mirror the impl's exact guard (`hv["_season_id"]` = open season at record time; `alloc["status"] == "PROJECTED"` check at `routes_field.py:262`).

## Step 9: Complete PRD — 2026-08-10T12:00:00.000Z

PRD_COMPLETED.md is complete. Summary:

**Files**
- Source: `/home/ubuntu/github/CodingPRD/tasks/task_0983_beehive_hosting_backyard_hive/workspace/PRD_FINALIZED.md` — 350 lines, 54,114 chars
- Output: `/home/ubuntu/github/CodingPRD/tasks/task_0983_beehive_hosting_backyard_hive/workspace/PRD_COMPLETED.md` — 351 lines, 56,263 chars (+1 line, +2,149 chars)

**Counts**: 22 ambiguity-pins, 4 mismatch-revisions (26 edits total; all inline in existing paragraphs/table rows, no new sections).

**Ambiguity-pins (insert)**
- §2.2 — insert — ambiguity — undefined path/unsupported method → `ERR_NOT_FOUND` (404) in the standard envelope — app.py:32-39
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` falls back to default, out-of-range values clamped, not rejected — response.py:52-68
- §2.3 — revise — ambiguity — list sort ties broken by creation order — services.py:23
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — util.py:67
- §2.7 — revise — ambiguity — both posture variants (not just `posture`) recomputed lazily on every hive read — services.py:141-143, routes_agreements.py:27-29
- §2.12 step 5 — revise — ambiguity — malformed JSON or non-object body fails as `ERR_INVALID_REQUEST` at the shape step — middleware.py:25-36
- §3.1 — revise — ambiguity — site unblock with a `REPORTED` incident → `ERR_SITE_HAS_OPEN_INCIDENTS`; unblock only from `BLOCKED` (else `ERR_INVALID_STATE`) — routes_core.py:202-213
- §3.1 — revise — ambiguity — incident terminal status names: `RESOLVED_AT_FAULT`, `RESOLVED_NO_FAULT`, `DISMISSED` — routes_ops.py:573-583
- §3.2 — revise — ambiguity — terminated agreement's resulting status is `TERMINATED` — routes_agreements.py:210
- §3.3 — revise — ambiguity — mark-dead from any state other than `ACTIVE`/`QUARANTINED` → `ERR_INVALID_STATE` — routes_agreements.py:314-315
- §3.4 — revise — ambiguity — inspection submit by non-recorder → `ERR_NOT_RESOURCE_OWNER`; submit admissible only from `DRAFT`/`RETURNED` (else `ERR_INVALID_STATE`) — routes_field.py:79-82
- §3.4 — revise — ambiguity — posture candidate ordering: further ties after `created_at` broken by creation order, latest first — services.py:129
- §3.5 — revise — ambiguity — harvest approval when no season is `OPEN` updates only the harvest; no allocation created or recomputed — routes_field.py:293-314
- §3.7 — revise — ambiguity — capture/mark-lost by a non-assigned beekeeper → `ERR_NOT_RESOURCE_OWNER` — routes_ops.py:106,146
- §3.8 — insert — ambiguity — cancellation-fee adjustment invoice is written against the host's non-`CANCELLED` subscription; if none exists the fee is never invoiced — services.py:410-418
- §3.9 — revise — ambiguity — change-plan requires subscription `ACTIVE` (else `ERR_SUBSCRIPTION_NOT_ACTIVE`) — routes_ops.py:357-358
- §3.9 — revise — ambiguity — failing quiz outcome lands enrollment in `FAILED`; passing in `COMPLETED` — routes_ops.py:503-507
- §4 (10 rows) — revise — ambiguity — named each list endpoint's actual filters: agreements (`host_id`,`site_id`), inspections/treatments/harvests/removal-jobs (`hive_id`), swarms (`site_id`,`source_hive_id`), subscriptions/enrollments (`host_id`), invoices (`subscription_id`), incidents (`site_id`,`host_id`) — routes_*.py list handlers

**Mismatch-revisions (revise)**
- §2.8 — revise — mismatch — replaced the pinned recompute-trigger list with live derivation: `effective_capacity_hives` is computed on every site read and gate evaluation (impl never stores it authoritative; e.g. subscription cancellation takes effect immediately) — services.py:78-85, routes_core.py:29-32
- §3.2 — revise — mismatch — creation gate order pinned as impl does it: `ACTIVE` check first, then reputation ≥ 50 (PRD listed reputation first) — routes_agreements.py:76-79
- §3.3 — revise — mismatch — install gate listing reordered to the true pipeline order impl executes (agreement-ACTIVE state → waiver → site `CLEAR`/capacity → term window → host `ACTIVE`); PRD had claimed host-ACTIVE second — routes_agreements.py:240-258
- §3.4 — revise — mismatch — `last_verified_inspection_at` is set to the latest verified inspection's `inspected_at` per candidate ordering, not necessarily the just-verified inspection's (differs when inspections verify out of order) — services.py:251-252

Everything else walked (state machines, posture ladder thresholds, net_kg/mite-load/share/waterfall math, invoice line math and late-fee compounding, rollover sweep steps and order, crew buffer and 48h/24h/72h boundaries, SoD walls, OCC guards, all endpoint role lists, error catalog statuses) already matched PRD prose uniquely and was left unchanged.
