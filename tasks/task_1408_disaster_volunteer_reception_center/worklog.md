# Worklog — task_1408_disaster_volunteer_reception_center

## Step 1: Create Task Directory — 2026-08-13T04:05:00.000Z

Directory `tasks/task_1408_disaster_volunteer_reception_center/` with `workspace/` pre-created and pre-assigned by the pipeline launcher (Step 1 treated as DONE per command args).

## Step 2: Generate Scaffold — 2026-08-13T05:21:00.000Z

Scaffold generation complete. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_1408_disaster_volunteer_reception_center/` and the linter verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts**
- Entities: 13 (Incident, Volunteer, SkillCredential, BackgroundCheck, Clearance, SupportRequest, SiteShift, DeploymentAssignment, TransportTrip, SeatBooking, PPEIssuance, HourEntry, RiskReport)
- Endpoints: 75 (action-heavy, minimal-CRUD surface under flat `/vrc/*` collections)
- State machines: 13 (Volunteer cyclic suspension/re-vetting loop; Incident parallel lifecycle × posture dimensions; HourEntry SUBMITTED⇄DISPUTED cycle with two-dispute termination)
- Calculations: 11 (2 dual-variant: cost-share provisional/verified + risk current/lifetime)
- Validations: 15 priority tiers (auth → role → existence → shape → lifecycle → posture → state → SoD → safety → referential → temporal → constraint → fiscal)
- Errors: 44 (all referenced; zero unreferenced)
- Roles: 8 (Volunteer is `entity_backed:Volunteer`; 7 opaque staff roles; segregation-of-duties model with 3 explicit SoD rules)
- Concurrency rules: 2 (OCC on `Volunteer.version` PATCH and `SupportRequest.version` PUT, 412/ERR_STALE_VERSION)
- §1.8 difficulty instances: 18 (9 rules × 2)
- §1.9 corner instances: 64 (61 active + 3 `excluded_because` stubs), 1,440 total structured calls lint-checked

**Notable design decisions**
- Archetype: workflow orchestration + compliance/audit; layers: optimistic concurrency, cascading side effects, dual-variant calculation, selector policy (deterministic auto-match: fewest verified hours → created_at → name; never id).
- Logical clock `POST /vrc/_clock/set_current_utc` with pinned startup default `2026-08-01T00:00:00Z`; clock-set drives expiry sweeps (credentials, background checks, briefings) and posture recomputation.
- Difficulty anchors: FEMA cost-share rounding pinned per-share with local-remainder absorption (10500 → 7875/1313/1312); ADVANCED OT split (10.5h → 54050 cents); inclusive boundaries (committed hours == 40.00 allowed, seats == capacity allowed, briefing expired exactly at valid_until); two interval semantics (half-open volunteer shift overlap vs 45-minute vehicle turnaround buffer); depth-5 risk-substantiation suspension cascade vs depth-4 shift-cancel cascade; recognition GOLD tier capped by lifetime risk.
- Fixed during self-review: sub-resource path params renamed to `{id}` for lint check (f); vehicle-turnaround formula aligned with the 45-minute boundary test; gold-tier chain re-sequenced so confirms interleave with completions (respects the 40h cap); briefing refreshes repositioned ahead of check-ins; forbidden race vocabulary eliminated; all 44 error codes wired into validations/transitions.

## Step 3: Copy Shared Files — 2026-08-13T05:22:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1408_disaster_volunteer_reception_center/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T05:45:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1408_disaster_volunteer_reception_center/workspace/PRD.md` (335 lines, ~5,900 prose words; 8,175 by `wc -w` including table cells). The two forbidden index files were never opened.

### Section list

- §1 Introduction (2 paragraphs — operational context, then the life-safety/auditability framing)
- §2 Global Specifications: 2.1 RBAC (all 8 roles with identity translations), 2.2 API Response Structure (byte-identical to canonical source, verified by diff), 2.3 Pagination & List Filtering, 2.4 The Logical Clock, 2.5 Common Resource Properties, 2.6 Derived Counters & Automatic State Reconciliation, 2.7 Lifecycle Gating & Operational Posture, 2.8 SoD & Volunteer Ownership, 2.9 OCC, 2.10 Money/Hours/Rounding, 2.11 Validation Pipeline Ordering (all 15 priorities narrated in order)
- §3 Business Logic: 3.1 Incident stand-up/close-down, 3.2 Intake & credentialing pipeline, 3.3 Requests/shifts/matching (incl. full auto-match selector policy), 3.4 Field operations (check-in, trips, seats, PPE), 3.5 Hour accounting & cost-share, 3.6 Risk/suspension/demobilization
- §4 Endpoint table (75 endpoints, 4 columns) — §5 Error catalogue (44 errors, 2 columns)

### Hard-contract reports

- **Contract 1 (field names):** 79 entity fields, 47 request-body ids, 15 query params, 14 path params — 0 missing in all four sets. PASS (two passes; first pass flagged everything due to §2.2 JSON fences scrambling naive backtick pairing — fixed the checker by stripping fenced blocks, not the PRD).
- **Contract 2 (rules):** 15 validation priorities expressed in ordered prose; 2 OCC rules (endpoint + `expected_volunteer_version`/`expected_support_request_version` + `ERR_STALE_VERSION`/412 each); all 60+ state transitions with preconditions/side-effects (suspension and shift-cancellation cascades rendered step-by-step in exact order); all 11 calculations in reconstruction-safe prose (no operator syntax, no fuzzy words — mechanically scanned); all `applies_to` scopes enumerated; sibling branches (4-state suspend/withdraw, 3-state demobilize/cancel, 3 PPE outcomes) given equal density. PASS.
- **Contract 3 (§3 path purity):** 614 backtick tokens scanned in §3 — 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. PASS.

### Zero-silence rules applied

Every error id's trigger sits near its workflow; every cascade lists all secondary mutations; validation priority stated as an ordered pipeline; OCC framed purely as stale-version rejection; all defaults/nullables stated (share fields at 0, `recognition_tier` default `NONE`, `valid_until` null on waivers, etc.); FROZEN-before-RESTRICTED evaluation order and ACTIVE-only posture gating made explicit.

### Scaffold ambiguities resolved in prose

1. **PATCH/credential ownership:** the RBAC matrix hints "self; ownership-checked" but P8's enforceable SoD/ownership list omits PATCH and credential claims — I asserted ownership rejections only for the five scaffold-named operations (accept/decline/resubmit/withdraw/hour-entry create) and described credential self-claims descriptively, avoiding inventing a rule.
2. **DEMOBILIZATION write scope:** P5's permitted list vs. the error catalog's rejected-examples list don't cover every endpoint (e.g., risk-report filing, clearance revoke) — I rendered both scaffold lists verbatim in prose without adjudicating the unlisted cases.
3. **Auto-match on non-OPEN requests:** scaffold gives only the "OPEN → MATCHING when ≥1 placement" side effect; I stated exactly that without inventing status preconditions.
4. **Auto-match ranking "(last_name, first_name)"** vs. the Volunteer having only `full_name` — rendered as "last name and first name in ascending lexicographic order" without inventing fields.

## Step 5: Generate Unit Tests — 2026-08-13T06:10:00.000Z

All checks pass. Final state verified: 103 tests collected, coverage audit PASS, verbatim-citation grep PASS, hygiene PASS.

### Summary

**Task:** task_1408_disaster_volunteer_reception_center — full test infrastructure generated from the two design indices under the design-index-only contract.

**Stage 1 — `test_helpers/` (9 files):**
- `types.py` — 13 entity TypedDicts + 20 enums (statuses, roles, skill/hazard/severity domains)
- `api_client.py` — `ApiClient(GenericApiClient)` with 48 endpoint methods covering every PRD §4 route
- `api_errors.py` — all 44 error IDs with PRD §5 HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + incident share-sum and risk-score invariant checkers
- `factories.py` — 13 payload factories (input fields only)
- `constants.py` — rates (2800/4600), OT 8.0/1.5, 40h cap, risk thresholds (50/100), decay bands (168/720), tier thresholds, 45-min turnaround, etc.
- `test_users.py` — headers for all 8 roles + `make_volunteer_headers(id)` for the entity-backed Volunteer role
- `fixtures.py` — composite chains: `create_active_incident`, `vet_volunteer` (full readiness pipeline), `create_published_request`/`create_open_shift`, `propose_accept_confirm_assignment`, `check_in_and_complete` (tolerates still-valid briefings), `create_completed_assignment_with_entry`, `create_verified_entry`, `file_and_substantiate_report`

**Stage 2 — `test_suite/` (10 files, 103 tests):** `conftest.py` + `test_01_envelope_and_listing` (6), `test_02_incident_lifecycle_posture` (9), `test_03_volunteer_pipeline` (11), `test_04_security_and_concurrency` (10), `test_05_assignment_matching` (11), `test_06_assignment_lifecycle` (18), `test_07_transport_and_seats` (8), `test_08_hours_and_cost_share` (12), `test_09_risk_and_suspension` (11).

**Queue A (Difficulty):** 36 tests — all 18 instances × ≥2 tests, tags verbatim (including the literal `(mode a)` / `(mode b)` suffixes on the two `combinatorial_formula` names).
**Queue B (Corner):** 67 tests — all 61 non-stub instances × ≥1 test.

**Skipped instances (3, all `excluded_because:` stubs — not translated, pointers verified to resolve):**
- `calculations/committed_hours_cap_boundary` → owned by `committed_hours_exactly_40_allowed_40_25_rejected`
- `cross_cutting_layers/suspension_cascade_end_to_end` → owned by `risk_substantiation_triggers_suspension_cascade_depth5`
- `cross_cutting_layers/shift_cancel_cascade_end_to_end` → owned by `shift_cancel_triggers_release_cascade_depth4`

Zero non-stub instances failed the PRD-first filter — notably, both priority-pair instances survive because PRD §2.11 explicitly orders the validation pipeline ("reports the earliest failing stage").

**Self-check verdicts:** Stage 1 (helpers import cleanly, no framework re-implementation) PASS; Stage 2 PASS — no untagged/dangling/dual-tagged tests, every docstring carries a verbatim PRD citation (8-word-window grep against `workspace/PRD.md`: 103/103 hit), no skip/xfail markers, no scaffold references in comments, `pytest --collect-only` collects all 103 tests without error.

## Step 6: Generate Implementation — 2026-08-13T06:35:00.000Z

Implementation complete. All files live under `/home/ubuntu/github/CodingPRD/tasks/task_1408_disaster_volunteer_reception_center/workspace/implementation/`.

### File inventory (3,386 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded `pip install` (no-op once flask importable), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=3.0` |
| `app.py` | 52 | Flask assembly, ApiError/404/405/500 handlers emitting the PRD envelope, binds `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 102 | Empty in-memory stores (13 dicts), logical clock (startup default exactly `2026-08-01T00:00:00Z`, never wall-clock), ISO-8601 3-fractional-digit formatting/parsing |
| `errors.py` | 78 | Full 42-entry error catalog with exact ids and HTTP statuses |
| `response.py` | 95 | Envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields only on lists), limit/offset clamping (default 10, 1–100), `created_at`-ascending sort with insertion-seq tiebreak |
| `middleware.py` | 45 | Stage-1 header checks (`X-User-ID`/`X-User-Role`, 8 roles), stage-2 per-endpoint role authorization |
| `validation.py` | 146 | Stage-4 shape validation: required fields, strict types (bool rejected for ints), enums, hours `(0,16]` and 0.25-multiple via `Decimal`, `ppe_stock` exactly-five-keys rule, unknown-field rejection |
| `validators.py` | 169 | Stage-3 existence lookups, stage-5 lifecycle gate (DEMOBILIZATION whitelist → `ERR_INCIDENT_DEMOBILIZING`, else `ERR_INCIDENT_NOT_ACTIVE`), stage-6 posture gate, stage-9 assignment-safety chain (READY → skill → class → RED-hazard → BG freshness), site/window coherence |
| `services.py` | 782 | All calculations, derived counters, state reconciliation, cascades, serializers |
| `routes_core.py` | 467 | Incident lifecycle, clock-set + sweep, volunteer pipeline, OCC `PATCH`, all incident/volunteer reverse-channel lists |
| `routes_vetting.py` | 256 | Credentials (incl. EXPIRED→VERIFIED renewal), background checks (SoD, 720h expiry, flag cascades), clearances (72h briefing validity, revoke regressions) |
| `routes_requests.py` | 291 | Support-request CRUD/OCC `PUT`, publish, auto-match selector, cancel/complete cascades |
| `routes_field.py` | 640 | Shifts, assignments (propose→accept→confirm→check-in→complete/no-show/recall/cancel), trips, seat bookings, PPE issue/close |
| `routes_hours_risk.py` | 252 | Hour entries (submit/verify/dispute×2/resubmit), risk reports (substantiate/dismiss with auto-suspension) |

### Organization of the hard parts

- **State machines**: each transition endpoint validates in PRD §2.11 pipeline order (auth → role → existence → shape → lifecycle → posture → state → SoD/ownership → safety → gate-docs → referential → temporal → uniqueness → capacity → auto-match non-empty). Automatic transitions (`VETTING↔CLEARED`, `READY↔DEPLOYED`, `OPEN/MATCHING/FILLED`, `OPEN_FOR_ROSTER↔LOCKED`) live in `services.py` as `reeval_volunteer_clearance`, `maybe_undeploy`, `recompute_request_status`, `recompute_shift_status`.
- **Calculations**: `Decimal`-only money/hours. Entry value `round_half_up(normal·rate + ot·rate·1.5)` per entry (2800/4600¢, 8.0h OT threshold, ×1.5); rollup sums integer cents with federal (×0.75) → state (×0.125) → local-by-subtraction pinned order; risk scores with step decay (<168h full, <720h `points//2`, else 0) computed lazily from substantiated reports + no-show events; recognition tiers with inclusive boundaries and GOLD→SILVER cap at lifetime ≥20; posture derivation (FROZEN on 24h CRITICAL substantiation strictly before RESTRICTED at ≥3 unfilled CRITICAL or open RED shift); 40.00-hour cap with inclusive equality; half-open shift overlap (adjacency legal); vehicle turnaround with exactly-45-min buffer legal; auto-match ranking `verified_hours_total → created_at → (last, first) name`, never ids.
- **Cascades** (exact spec order): suspension, withdrawal release, request cancel, shift cancel (assignments → trips → bookings → posture), trip cancel, waiver-revoke regressions, clock-set expiry sweep with CLEARED→VETTING regressions and all-ACTIVE-incident posture recompute (FROZEN thaws as the 24h window passes).
- **Versioning/OCC**: every mutation bumps `version` +1 and refreshes `updated_at` from the logical clock, coalesced to one bump per resource per API call via a request-scoped touched set; derived-counter recomputes count as mutations (so auto-match/confirm stale out `expected_support_request_version`, per the scaffold's OCC notes).

### Boot verification

`bash start.sh` was cold-booted three times in a fresh process: it binds `0.0.0.0:$PORT`, answers HTTP in ~1s, starts with the store empty and the clock at `2026-08-01T00:00:00Z` (verified after kill/restart — no carry-over state, no seeding anywhere). 182 end-to-end smoke assertions across four scenarios pass: auth/RBAC, shape and 404 ordering, the full REGISTERED→…→READY pipeline, SoD violations, OCC 412s, propose/confirm/check-in/complete with LOCKED/FILLED reconciliation, RESTRICTED/FROZEN posture gates and thaw, auto-match placement/ranking/`ERR_NO_ELIGIBLE_PLACEMENTS`, dispute→resubmit→REJECTED_FINAL rollups (verified cents math 40250 → federal 30188/state 5031/local 5031), decay boundaries at exactly 168h/720h, blacklist at lifetime ≥100, the DEMOBILIZATION write whitelist, and a full incident close-out to `CLOSED`.

## Step 7: Test/Iterate Loop — 2026-08-13T06:55:00.000Z

All 8 parallel rounds pass 103/103. The task is complete.

### Summary

**Iterations run:** 3 full sweeps (1 baseline sweep identifying 8 failing tests, 1 sweep invalidated by a transient start.sh regression I introduced and immediately fixed, 1 final clean sweep: 8/8 rounds × 103/103 tests, zero flakes).

**Tests deleted:** None. Every failing test traced to verbatim PRD prose and was faithful in setup, request, and assertion.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1408_disaster_volunteer_reception_center/test_helpers/fixtures.py` — `create_completed_assignment_with_entry`: now issues PPE only when the volunteer holds no `ISSUED` record. The helper unconditionally issued 1 unit per call; recognition-tier tests call it in a 3-4 day loop against `ppe_stock` of 2, so the PRD-required stock check (`ERR_PPE_STOCK_INSUFFICIENT`) correctly rejected iteration 3. The PRD check-in gate requires only "at least one PPE issuance still `ISSUED` for the volunteer", so re-issuance was unnecessary. Fixed `test_recognition_tier_silver_at_exactly_24_verified_hours` and `test_recognition_tier_gold_capped_to_silver_by_lifetime_risk` (8/8 rounds).

**Fixes applied to `test_suite/`:**
- `test_02_incident_lifecycle_posture.py` — module-level helper `_critical_report_substantiated` referenced the `api` pytest fixture as a global (`NameError: name 'api' is not defined`); added `api` as its first parameter and updated the 3 call sites. Fixed 3 posture tests (8/8 rounds).
- `test_03_volunteer_pipeline.py` — added missing `RISK = TEST_USERS["risk_headers"]` constant (`NameError` at the waiver-revocation test, 8/8 rounds).

**Fixes applied to `implementation/`:**
- `workspace/implementation/db.py` — `new_id()` returned `uuid.uuid4().hex` (32 hex chars, no dashes); the suite's shared `is_valid_uuid` check (PRD §2.5 "server-minted UUID") requires canonical dashed form. Now returns `str(uuid.uuid4())`. Fixed `test_create_incident_applies_computed_defaults` (8/8 rounds).
- `workspace/implementation/start.sh` — replaced the per-boot `python3 -c "import flask"` guard with a one-time `.deps_installed` marker check, halving interpreter boots per restart. Root cause of the residual 8/8-round flake (`test_vehicle_turnaround_allows_exactly_45_minute_gap`, and earlier `test_substantiation_past_threshold_auto_suspends_and_cancels_work`): the runner's per-test restart poll allows 15s; on this host (~96 concurrent pipeline agents, 32 cores) simultaneous multi-round boots sporadically exceeded that window. With the faster boot, the flake disappeared and per-round wall time dropped to ~74s.

**Key findings:** the union-of-8-rounds protocol was essential — the baseline sweep showed one failure mode (posture/test_02 cluster) that looked flaky in the killed first attempt (5-7 of 8 rounds) but was deterministic, plus a genuinely environmental restart flake that moved between tests across sweeps until the boot-time fix eliminated it.

## Step 8: Finalize PRD — 2026-08-13T07:05:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1408_disaster_volunteer_reception_center/workspace/PRD_FINALIZED.md` written with exactly one inline revision.

### Summary

**Line counts / %-delta:** PRD.md 335 lines (59,780 chars) → PRD_FINALIZED.md 335 lines (59,976 chars); +0.33% characters, one line modified in place (§2.5, line 86).

**Changes:**
- §2.5 Common Resource Properties — revise — the `id` sentence now pins the wire format: "rendered in the canonical 36-character hyphenated form — five groups of 8, 4, 4, 4, and 12 lowercase hexadecimal digits separated by hyphens (for example, `3f6b8f2e-4c1a-4f7b-9c2d-1a2b3c4d5e6f`)" — `implementation/db.py:55-56` (`new_id()` returns `str(uuid.uuid4())`; the old PRD phrase "server-minted UUID" did not determine dashed-canonical vs 32-char dashless hex, which is what Step 7 fixed in the impl).

**Step_7_diff items that required no PRD edit (and why):**
- `test_helpers/fixtures.py` PPE re-issuance — pure fixture bug. PRD §3.4 (line 172) already pins the check-in gate as "at least one PPE issuance still `ISSUED` for the volunteer" (impl `routes_field.py:303-304`, `svc.has_issued_ppe`), and §3.5 (line 180) already pins the stock check "issuing exactly the remaining units is allowed, while one unit more fails with `ERR_PPE_STOCK_INSUFFICIENT`" (impl `routes_field.py:607-609`). Impl behavior was unchanged; PRD already matches verbatim.
- `test_02_incident_lifecycle_posture.py` (`api` param) and `test_03_volunteer_pipeline.py` (`RISK` constant) — pure test-code NameErrors, no PRD semantics involved.
- `implementation/start.sh` dep-check marker — boot-performance infrastructure only; the PRD governs API behavior, not process bootstrap. Nothing in the PRD constrains or describes this.

**Per-edit pre-edit search log:**
1. Edit: §2.5 `id` format sentence.
   - (a) Subject: wire representation of server-minted `id` values.
   - (b) Impl paths enumerated and read/grepped: `db.py:9,55-56` (sole minting function, `str(uuid.uuid4())` → lowercase 8-4-4-4-12); `services.py:55-66` `create_record` (generic creation primitive minting `id` for all 13 stores); all 15 creation call sites grepped (`routes_core.py:50` incidents, `routes_core.py:225-239` volunteers via `db.new_id()` directly, `routes_vetting.py:63,136,222` credentials/background_checks/clearances, `routes_requests.py:65,225` support_requests/auto-match assignments, `routes_field.py:83,170,393,501,611` shifts/assignments/trips/seat_bookings/ppe_issuances, `routes_hours_risk.py:70,189` hour_entries/risk_reports) — all funnel through `db.new_id()`, so a universal "every resource" claim holds; consumers: `validators.py:24-28` `get_or_404` and `load_fk_string` (plain dict-key lookups, no format validation of client-supplied ids), Flask path converters (untyped strings), `middleware.py:23-33` (`X-User-ID` treated as opaque string, no UUID check); serializers (`services.py:579` and sibling views) emit `rec["id"]` verbatim. Cross-checked the test-side oracle `prd_bench_local_runner/testing/assertions.py:19-30` (`is_valid_uuid` = case-insensitive 8-4-4-4-12 dashed regex).
   - (c) Wording adjustment: kept the revision scoped strictly to *server-minted* ids (the original sentence's scope) so it says nothing about validating client-supplied path/body ids or the `X-User-ID` header — consistent with the enumerated consumer paths, which do no format validation. "Lowercase" matches `str(uuid.uuid4())` output exactly; an example was added so a fresh implementer cannot choose the dashless `uuid4().hex` form again.

## Step 9: Complete PRD — 2026-08-13T07:20:00.000Z

Section structure unchanged. Task complete.

### Summary

**Source vs output**: `PRD_FINALIZED.md` (335 lines / 60,179 bytes) → `PRD_COMPLETED.md` (336 lines / 64,552 bytes); char delta **+4,335 chars (+4,373 bytes)**. 27 inline edit hunks; no new sections, no new paragraphs (one added bullet inside the existing §2.2 bullet list).

**Counts**: 22 ambiguity-pins, 5 mismatch-revisions (two hunks carry both a pin and a revision, counted by their dominant change).

### Changes

- **§2.2** — insert — ambiguity — unknown path / unsupported method answered with `ERR_RESOURCE_NOT_FOUND` (404) in the standard envelope — `app.py:34-40`
- **§2.3** — insert — ambiguity — `limit`/`offset` out-of-range clamped to bounds, non-numeric falls back to defaults — `response.py:59-78`
- **§2.3** — insert — ambiguity — `created_at` ties ordered by creation (insertion) sequence, never `id` — `response.py:84`, `db.py:47-52`
- **§2.3** — insert — ambiguity — `has_more` true iff `offset`+`limit` < `total_count` — `response.py:93`
- **§2.3** — insert — ambiguity — filters match by exact equality; non-matching values yield empty pages; unrecognized query params ignored — `routes_core.py:153-192` etc.
- **§2.4** — insert — ambiguity — clock may be set to any valid instant, including earlier than the current reading — `routes_core.py:199-208`, `db.py:24-26`
- **§2.4** — revise — mismatch — posture re-derived for *every* incident on clock-set (was "each affected incident"), so postures thaw as the 24h window moves — `services.py:571-572`
- **§2.5** — insert — ambiguity — a resource's `version` rises at most once per API call regardless of how many mutations touch it — `services.py:69-76`
- **§2.8** — revise — mismatch — ownership list extended with OCC-guarded profile edit and credential claims — `routes_core.py:267-268`, `routes_vetting.py:61-62`
- **§2.9** — insert — ambiguity — a successful edit bumps `version` even when no editable field changes — `routes_core.py:275`, `routes_requests.py:124`
- **§2.11 stage 4** — insert — ambiguity — required strings non-empty; booleans never satisfy integer fields; non-object JSON body is `ERR_INVALID_REQUEST`, absent/unparseable body treated as empty object — `validation.py:22-29, 42-68`
- **§2.11 stage 4** — revise — mismatch — unknown-field rejection scoped to endpoints that declare a payload; action endpoints ignore extra body fields — `validation.py:36-39` vs. `get_body()`-only action handlers (e.g. `routes_core.py:75`)
- **§2.11 stage 11** — insert — ambiguity — hour-entry `work_date`-equality and hours-vs-`duration_hours` rules sit at the referential-coherence stage (after ownership, before uniqueness) — `routes_hours_risk.py:61-69`
- **§3.2** — insert — ambiguity — credential renewal restores `VERIFIED` without altering `expires_at` — `routes_vetting.py:95-98`
- **§3.2** — insert — ambiguity — flagging the pending check of a volunteer in any other status (e.g. already `SUSPENDED`) changes no volunteer status; only posture is re-derived — `routes_vetting.py:188-196`
- **§3.2** — insert — ambiguity — a clearance may be recorded for a volunteer in any status — `routes_vetting.py:202-230`
- **§3.3** — insert — ambiguity — request edit re-validates end-after-start against the merged window — `routes_requests.py:103-106`
- **§3.3** — insert — ambiguity — the 0.25-hour minimum is evaluated against the rounded `duration_hours` — `routes_field.py:78-80`
- **§3.3** — insert — ambiguity — shift's own `CANCELLED` is stamped after the cascade, so step four's posture re-derivation observes the pre-cancellation status — `routes_field.py:132-135`, `services.py:474`
- **§3.3** — insert — ambiguity — proposal requires the request `OPEN`/`MATCHING`; imposes no shift-state precondition; cross-incident shift/volunteer fails as `ERR_SITE_WINDOW_MISMATCH` — `routes_field.py:163-167`
- **§3.3** — insert — ambiguity — confirm preconditions evaluated in listed order, placing shift-state and roster-capacity checks ahead of the safety re-run — `routes_field.py:250-262`
- **§3.3** — insert — ambiguity — auto-match requires the request `OPEN` or `MATCHING` — `routes_requests.py:154-155`
- **§3.3** — insert — ambiguity — auto-match tops up to `headcount_needed` counting live assignments in `PROPOSED`/`ACCEPTED`/`CONFIRMED`/`CHECKED_IN`/`COMPLETED`; `remaining_need` defined accordingly — `routes_requests.py:157-159, 243-245`
- **§3.3** — insert — ambiguity — last/first name for ranking are the last/first whitespace-delimited tokens of `full_name` — `routes_requests.py:183-187`
- **§3.4** — insert — ambiguity — check-in window inclusive at both ends (`start_at`−30min ≤ now ≤ `end_at`) — `routes_field.py:306`
- **§3.4** — insert — ambiguity — cross-incident shift on trip creation rejected as `ERR_RESOURCE_NOT_FOUND`; turnaround conflict scoped to same incident — `routes_field.py:389-390`, `services.py:501-510`
- **§3.4** — insert — ambiguity — no incident-coherence check between trip and assignment on seat booking — `routes_field.py:487-500`
- **§3.5** — insert — ambiguity — `work_date` must be a `YYYY-MM-DD` string — `routes_hours_risk.py:52-54`, `db.py:92-102`
- **§3.5** — revise — mismatch — qualifying credential is not unique: highest class wins, earliest `created_at` breaks ties, falls back to any matching credential, `STANDARD` rate when none — `services.py:170-196`
- **§3.6** — insert — ambiguity — risk report may be filed against a volunteer in any status — `routes_hours_risk.py:174-201`
- **§3.6** — insert — ambiguity — reinstatement enforces the blacklist check before the pending-check requirement — `routes_core.py:344-348`
- **§3.6** — revise — mismatch — withdrawal cascade includes seat-booking cancellation (was "first, second, and fourth" steps) — `services.py:408-422`; also pins that waiver revocation outside `READY`/`DEPLOYED` has no volunteer-level effect — `routes_vetting.py:248-255`
