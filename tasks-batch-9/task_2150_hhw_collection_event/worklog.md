## Step 1: Create task directory — 2026-08-24T14:33:08.620114082Z

Created `tasks/task_2150_hhw_collection_event/` and `tasks/task_2150_hhw_collection_event/workspace/` (next index after highest existing task_2149_*).

## Step 3: Copy shared files — 2026-08-24T14:33:27.861948552Z

Copied `./INSTRUCTION.md` -> `tasks/task_2150_hhw_collection_event/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate scaffold — 2026-08-24T15:38:16.422015706Z

All three artifacts are written and verified. Final state:

## Files written

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2150_hhw_collection_event/SCAFFOLD.yaml` | 1970 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2150_hhw_collection_event/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1972 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2150_hhw_collection_event/SCAFFOLD_CORNER_DESIGN.yaml` | 3415 |

## Scaffold contents (§1.0–§1.7)

- **11 entities** (Program, Site, MaterialCategory, Resident, CollectionEvent, Staffer, LaneAssignment, Appointment, DropoffLine, PackedContainer, Manifest)
- **7 state machines** — including CollectionEvent's two *parallel* axes (`lifecycle_status` × `containment_status`), Manifest's DRAFT→SIGNED→SHIPPED→DISCREPANCY→DRAFT *cycle*, and Appointment's CONFIRMED⇄WAITLISTED cycle plus a CHECKED_IN/UNLOADING fork into {COMPLETED, REFERRED_OUT}
- **2 concurrency rules** (OCC on `Resident.version` for appointment-create supersede; OCC on `CollectionEvent.version` for manifest-create supersede)
- **8 calculations**, **31 validations** (strict priority ladder), **44 endpoints**, **39 error codes**, **8 roles** (segregation-of-duties model, one `entity_backed:Resident` + seven opaque)
- Profile: `compliance_audit` × `quota_allocation`, **flat** topology, **parallel** state-machine shape, self-referential `Site.replaces_site_id`, immediate consistency — deliberately the diversity-prioritized combinations

## Design indices

- **§1.8: 20 instances** across all 9 `rule_id`s (2 each, 3 for `combinatorial_formula` covering modes a/b/c)
- **§1.9: 64 instances** across 9 guide sections (60 full recipes + 4 `excluded_because` stubs)
- 89 uniquely-named instances total, 1012 API calls in setup/trigger chains

## Verification

`scaffold_lint.py` verdict, pasted verbatim:

```
Coverage
  §1.5 endpoints declared:    44
  §1.1 entities declared:     11
  §1.8 instances scanned:     20
  §1.9 instances scanned:     64
  Calls scanned (§1.8+§1.9):  1012

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional self-checks run: zero duplicate instance names, zero unbound `${var}` placeholders, every `excluded_because.difficulty_instance` resolves, all 39 error codes triggered by at least one design instance, no forbidden concurrency vocabulary.

## Key difficulty mechanics (literals pre-computed in Python, not estimated)

- Dual-variant costing: round-per-line-then-sum **699¢** vs sum-then-round blended **698¢** on identical 4.5 kg — 1¢ apart; a two-class variant gives **819 vs 818** at blended rate 172.1053
- Circular-looking contingency pinned by evaluation order: pre-contingency **301098** → contingency **24088** → total **325186** → cost/participant **325186**; tier-boundary case at exactly 2000.0 kg gives **458352**
- Three-leg `min()` capacity: **48** COMPLIANT / **0** DEFICIENT / **25** REMEDIATED from the same lanes and hours
- Two depth-4 cascades from different triggers (containment FAIL → posture RESTRICTED; event CANCEL → posture back to OPEN)
- Two interval geometries: staffer half-open + 30-min trailing buffer (12:29 rejected, 12:30 accepted) vs site closed-interval + symmetric 48 h buffer (20:00 rejected, 20:01 accepted) plus a 2-per-month aggregate cap

Two declared transitions (`RECONCILE`, resident `REINSTATE`) are reachable and enum-closed but not exercised by a design instance — the only deliberate breadth gap.

## Step 4: Generate PRD — 2026-08-24T15:50:29.146834489Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2150_hhw_collection_event/workspace/PRD.md` — **482 lines, ~102 KB**. Written incrementally (Write for §1–2.1, then six separate appends), so nothing was lost to the output cap. Neither design index was opened.

**Document skeleton**: §1 three-paragraph intro; §2 with ten subsections (2.1 RBAC, 2.2 fixed envelope, 2.3 Pagination, 2.4 Resource Identity/Timestamps/Version, 2.5 Request Validation Order, 2.6 Precision & Units, 2.7 Stale-Version Guards, 2.8 Program Posture, 2.9 Logical Clock, 2.10 Cascade Ordering & Atomicity); §3 with nine workflow subsections following the program -> site -> event -> roster -> resident -> containment -> unload lane -> manifest -> report timeline; §4 4-column table; §5 2-column table.

**Per-section coverage checklist**

| Scaffold section | Count | Where represented |
| --- | --- | --- |
| entities | 11 | §3.1–3.9 (all 114 field names in prose) |
| state_machines | 7 axes / **52 transitions** | Site §3.2, Resident §3.5+§3.7, Event lifecycle §3.3, Event containment §3.6, Appointment §3.5+§3.6+§3.7, PackedContainer §3.8, Manifest §3.8 |
| calculations | 8/8 | slot_capacity §3.4, disposal_cost_valuation §3.8, quota_ledger §3.5, disposition_ladder §3.7, waitlist_sweep §3.6, staff_hours_ledger §3.4, cost_rollup §3.9, program_posture §2.8 |
| validations | 31/31 | §2.5 numbered ladder + conditions restated at each workflow |
| concurrency_rules | 2/2 | §2.7 (both name the write op, the `expected_*_version` field, `ERR_STALE_VERSION`, HTTP 412) |
| endpoints | 44/44 | §4 table; 23 side-effect sets narrated in §3 |
| errors | 39/39 | §5 table; all 39 also referenced in §2/§3 prose |
| roles | 8/8 | §2.1, incl. every `identity:` translated (7 opaque, `Resident` entity-backed) |

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 114 required, 114 present, 0 missing
- endpoints[].request_body: 83 required, 83 present, 0 missing
- endpoints[].query_params: 22 required, 22 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 31 checked, 31 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 52 checked, 52 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed, 0 missing
- validations[] conditions: 31 checked, 31 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 23 checked, 23 expressed, 0 missing
- entities[].fields[] structured content: 114 checked, 114 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked, 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 861
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 byte-identical to `section-2.2-response-structure.md`; all state enum values and all `type: enum` field values appear verbatim; zero fuzzy/approximating words and zero pseudocode operators in prose; §4 exactly 4 columns / 44 rows, §5 exactly 2 columns / 39 rows; file ends at §5 with no audit footer. One scaffold-internal reference (`calculations.program_cost_rollup`) leaking through an endpoint description was rewritten as a §3.9 cross-reference.

**Orchestrator verification**: grep-confirmed §4 table = 44 endpoint rows + 2 header rows, §5 table = 39 error rows + 2 header rows; no truncation of sections 4–5.

## Step 5: Generate unit tests — 2026-08-24T16:18:33.476234888Z

Test infrastructure and suite are complete and audited.

## Files written

**`test_helpers/`** (2,091 lines)
| File | Lines |
|---|---|
| `types.py` | 445 |
| `api_client.py` | 208 (one method per each of the 44 endpoints) |
| `api_errors.py` | 92 (all 39 error ids + status map, registered with the framework) |
| `assertions.py` | 260 |
| `constants.py` | 123 |
| `factories.py` | 138 |
| `fixtures.py` | 690 |
| `test_users.py` | 85 |
| `__init__.py` | 50 |

**`test_suite/`** (3,325 lines, 104 tests)
`conftest.py` (56) · `test_01_program_setup_and_catalogue.py` (233/10) · `test_02_site_selection_and_containment_screen.py` (358/12) · `test_03_event_scheduling_and_lifecycle.py` (473/16) · `test_04_lane_staffing_and_slot_capacity.py` (295/10) · `test_05_resident_registration_and_booking.py` (315/10) · `test_06_confirmation_capacity_and_waitlist.py` (582/16) · `test_07_unload_lane_and_screening_ladder.py` (306/8) · `test_08_labpack_containers.py` (246/8) · `test_09_manifest_and_disposal_settlement.py` (359/11) · `test_10_program_cost_report.py` (102/3)

## Tests per queue
- **Queue A (Difficulty): 40 tests** — exactly 2 per instance across all 20 instances.
- **Queue B (Corner): 64 tests** — exactly 1 per non-stub instance across all 64.

## Skipped instances
**None.** Every non-stub instance in both indices passed the PRD-first two-condition filter and was translated. The 5 `excluded_because:` corner stubs (`certified_staff_hours_excludes_released_assignments`, `container_and_manifest_cost_variant_divergence`, `cascading_side_effects_reach_three_or_more_entities`, `dual_variant_calculation_layer_divergence`, `confirm_response_immediately_reflects_reservation`) were not translated per §2.1; all five `difficulty_instance` cross-references resolve to real §1.8 instances.

## Verification run before exiting
- `python3 -m compileall` clean over both directories; `pyflakes` reports no undefined names (only benign barrel-export re-exports).
- `pytest --collect-only` collects **104 tests**, so every module imports and parses whole — no truncation.
- Automated audit script confirmed: every test carries **exactly one** `Design:` line, every tag resolves to a real instance, no stub tag used, difficulty >=2 / corner >=1 satisfied with zero shortfalls.
- Citation audit: every quoted docstring segment (>=8 chars) survives a whitespace-normalised literal match against `workspace/PRD.md` — **0 non-verbatim citations**. Three fragment citations in `test_06` were upgraded to the full confirmation-precondition sentence to satisfy C3.
- No `skip` / `skipif` / `xfail` anywhere; no "scaffold"/§1.x/table references leaked into generated comments.

Two composite fixtures were added beyond the canonical pipeline because several instances share them: `setup_two_confirmed_appointments` / `setup_deficiency_cascade_scenario` (the depth-4 containment cascade and the waitlist sweep) and `setup_two_class_manifest` (the two-rate-class blended-rate arithmetic). The pipeline itself is `setup_canon(n)`, a 32-step walk from programme creation to manifest receipt that every other test stops partway through.

## Step 6: Generate implementation — 2026-08-24T16:21:06.263749565Z

The implementation is complete and verified.

## What was built

`tasks/task_2150_hhw_collection_event/workspace/implementation/` — Python + Flask, 21 modules + `start.sh` + `requirements.txt`, **3,417 lines**:

| Layer | Files |
|---|---|
| Launcher | `start.sh` (guarded `pip install`, `exec python3 app.py`, `0.0.0.0:$PORT` default 10000), `requirements.txt` |
| Core | `app.py` (90), `store.py` (139), `errors.py` (94), `envelope.py` (91), `validation.py` (264), `common.py` (41) |
| Domain logic | `calc.py` (118), `rollups.py` (488), `cascades.py` (164), `serializers.py` (221) |
| Routes (44 endpoints) | `routes_program/site/material/resident/event/staff/appointment/dropoff/container/manifest/clock.py` |

## Boot verification

Three consecutive cold boots on a free port: **ready in 0.68 s each**, HTTP 200, and `GET /hhw/sites` returned `total_count: 0` with an empty array every time — confirming the store starts empty on every process and nothing is seeded or persisted (grep confirms no sqlite/file/JSON-dump paths). `pyflakes` is clean.

## Correctness testing

Five hand-written scenario suites (~250 assertions) all pass, including every PRD worked example verbatim: `slot_capacity` 48 compliant / 25 remediated; container estimate **699** (round-per-line-then-sum) vs manifest invoice **698** at blended rate 155.0000 (sum-then-round-once); cost report 698 -> 250000 mobilisation -> 301098 pre-contingency -> 24088 contingency -> **325186** total and per participant. Also verified: the 4-level containment-deficiency cascade with a partial waitlist sweep that stops exactly at the capacity line and skips `CAPACITY`-reason entries; site-suspension cascade; no-show -> auto-suspension -> cancellation of other appointments; manifest supersede/void, discrepancy, reopen and budget-bucket movement; posture OPEN->RESTRICTED->FROZEN with alert counting and an override that lifts RESTRICTED but never FROZEN; closed 48 h site band, half-open 30-minute decon buffer (29 min refused, 30 min accepted), quarter-hour alignment measured from `window_start_utc`.

## Two judgement calls worth flagging

1. **Ladder placement of unlisted preconditions.** Preconditions with no dedicated error code (clock gates, `open_lane_count >= 1`, RECONCILE gates, SIGN/REOPEN gates, site RETIRE's live-commitment rule, "event must be IN_PROGRESS" for check-in/unload actions) all return `ERR_INVALID_STATE_TRANSITION`; where PRD §3 prose states an explicit order (e.g. START = clock -> containment -> lanes; OPEN_REGISTRATION = containment -> clock -> posture) I followed the prose over the numbered ladder, since the ladder does not rank them.
2. **Per-action role split extended beyond manifests/sites.** PRD §2.1 names only those two families, but the §1.7 RBAC matrix and the §4 endpoint description declare appointment actions as role-exclusive (WAITLIST/PROMOTE = clerk; CHECK_IN...NO_SHOW = UnloadTech), so those are enforced at rung 2 as `ERR_UNAUTHORIZED_ROLE`.

Also: logical-clock stamps (`check_in_utc`, `signed_at_utc`, `recorded_at`, `current_utc`) echo the instant exactly as the client set it, while `created_at`/`updated_at`/`api_request_timestamp` use the three-fractional-digit form the PRD pins for them.

## Step 7: Run tests and iterate — 2026-08-24T16:25:53.884552314Z

All 8 parallel rounds passed 104/104 on the first sweep. Exiting per protocol.

## Summary

**Iterations run:** 1. The initial 8-round parallel stability sweep came back fully green, so no diagnostic protocol steps were triggered.

| Round | Result |
|---|---|
| 1–8 | 104/104 passed, 0 failed, 0 errors, 0 skipped |

The union of failing tests across all 8 rounds is **empty** — no flakiness surfaced. All 8 rounds collected the same 104 distinct test names, so no round silently under-collected. Each round took ~130s wall time; the 8 concurrent runs claimed separate ports with no collisions.

**Tests deleted:** none. No test failed, so no PRD-coverage or unique-derivability adjudication was reached (STEP 1 is entered only for tests in the failing union).

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`:** none required.

### Adjudication of the two flagged judgement calls

Both were checked; neither caused a failure, and neither warranted a change.

1. **Preconditions with no dedicated error code -> `ERR_INVALID_STATE_TRANSITION`** — **Correct as implemented.** PRD §2.5 rung 9 covers it verbatim: *"The requested action is a declared transition out of the target row's current state on the relevant axis — otherwise `ERR_INVALID_STATE_TRANSITION` (HTTP 409). ... The rule guards site transitions, event lifecycle transitions, appointment transitions..."*. The affected preconditions (site RETIRE with live events, `START_UNLOAD` needing a staffed lane, `COMPLETE_UNLOAD` needing >=1 line) have no dedicated code in the §5 catalogue, so this is the only consistent reading. `test_retiring_a_site_that_still_hosts_a_planned_event_is_refused` confirms it.

2. **Per-action role split enforced at rung 2 for appointment actions** — **Not observable by the suite; left in place.** §2.1 names exactly *two* split-by-action families ("Manifest actions are split between two roles... The same split-by-action pattern governs site lifecycle actions"), and rung 2 says only "*and, on the manifest-action endpoint, for the specific action named*". Appointments are not in that list. However, the §4 endpoint table does assign roles per appointment action, and §3.5 states waitlisting *"is a clerk-only action"* — so the check is defensible prose-wise. Decisively: no test asserts on it in either direction, and every fixture already issues appointment actions under the correct role, so the check is never tripped. Removing it would be an unforced change to a passing implementation, and the cardinal rules forbid stripping a check that PRD arguably requires.

### Integrity checks

- **No `pytest.mark.skip` / `xfail` anywhere** in `test_suite/` or `test_helpers/`. The single grep hit is a string literal `"skipped resident ledger"` inside an assertion message in `test_06_confirmation_capacity_and_waitlist.py:337`, not a marker.
- **104 `def test_` functions defined = 104 collected and run** in every round — nothing silently deselected.
- **Storage is in-memory only.** `workspace/implementation/store.py` uses plain dicts keyed by server-minted UUID; grep for `sqlite`/`open(`/`json.dump`/`pickle`/`/tmp`/`shelve`/`redis` across the implementation returns nothing. No entity data is seeded, preloaded, or hardcoded at startup. The logical clock initializes to exactly `2026-08-01T00:00:00Z` per PRD §2.9.

No changes were made to any file in the task directory. The task is in a passing, stable state.

---

**Orchestrator independent verification** (green-first-sweep is the pattern that can mask a design-index leak, so this was checked directly rather than taken on report):
- Re-read all 8 `results.{1..8}.json` from disk: each reports `passed=104 / total=104 / failed=0`.
- Grepped `implementation/` for design-index fixture literals (`Arvada`, `Jeffco`, `Ralston`, the all-zero UUID) — **zero hits**, so no §1.8/§1.9 recipe content leaked into the implementation.
- Grepped `implementation/` for hardcoded expected result values (`325186`, `301098`, `24088`, `698`, `699`) — **zero hits**, so the worked-example numbers are computed, not memorised.
- Grepped `implementation/` for persistence (`sqlite`, `json.dump`, `pickle`, `shelve`, `/tmp`) — **zero hits**, confirming in-memory-only storage.

**Step 8 skip condition MET**: 0 iterations beyond baseline, 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes. Step 8 (PRD_FINALIZED.md) is skipped; Step 9 runs from `PRD.md`.

## Step 8: Finalize PRD — 2026-08-24T16:36:29.629946833Z

**SKIPPED** — skip condition met. Step 7 exited on the first 8-round sweep with 0 iterations beyond baseline, 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behaviour the tests exercised, so there was no Step 7 diff to patch against. `PRD_FINALIZED.md` is therefore intentionally absent, and Step 9 ran from `PRD.md` directly.

## Step 9: Complete PRD — 2026-08-24T16:36:29.629946833Z

Done. Server stopped; file verified intact.

## Summary

**Files** — source `workspace/PRD.md`: 482 lines / 103,816 chars. Output `workspace/PRD_COMPLETED.md`: 482 lines / 109,729 chars (**+5,913 chars**, 0 lines added — all edits are in-paragraph). Integrity verified: §1–§5 all present, 19 subsections, **44 endpoint rows**, **39 error rows**.

**Counts** — 23 edits across 22 lines: **17 ambiguity-pins**, **6 mismatch-revisions**.

Both named candidates were confirmed against a live server (started on port 18251, exercised, then stopped) rather than by code-reading alone.

### The two named candidates — adjudicated

1. **Undedicated preconditions -> `ERR_INVALID_STATE_TRANSITION`, with §3 narrative order winning over the §2.5 ladder.** Confirmed live: `OPEN_REGISTRATION` on a `PENDING_INSPECTION` pad with the clock already past `window_start_utc` returns `ERR_CONTAINMENT_DEFICIENT` (rung 12), not the clock error — the clock gate only surfaces once the pad reads `COMPLIANT`. So containment is genuinely tested before a rung-9-class gate.
2. **Per-action role checks on appointments are real and sit at rung 2.** Confirmed live: `WAITLIST`/`PROMOTE` by `Resident` -> `ERR_UNAUTHORIZED_ROLE`; `CHECK_IN` by `EligibilityClerk` -> `ERR_UNAUTHORIZED_ROLE`; `NO_SHOW` by `Resident` -> `ERR_UNAUTHORIZED_ROLE`; an unknown or absent `action` -> `ERR_INVALID_REQUEST` (role check reads the parsed body and defers unknown actions to rung 3).

### One notable extra mismatch found

**§3.1's "A newly created program starts fully open. Its `posture` is `OPEN`" is false for `budget_cents: 0`** — which the same paragraph explicitly permits. Verified live: such a program is created with `posture: FROZEN`, `version: 1`, `budget_alert_count: 0`, because §2.8's first freeze tier is `committed >= budget_cents` and `0 >= 0`. §2.8 was already correct; §3.1 was the mismatch, so §3.1 was revised.

### All changes

| § | Kind | Type | What changed | impl |
|---|---|---|---|---|
| §2.1 | revise | mismatch | "two families of endpoint" -> "three families" | `routes_appointment.py:48-58` |
| §2.1 | insert | mismatch | Appointment transitions named as the third split-by-action family with exact per-action role sets; action read from parsed body, so absent/undeclared action -> `ERR_INVALID_REQUEST` | `routes_appointment.py:48-58,184`; `validation.py:61-73` |
| §2.3 | insert | ambiguity | `created_at` ties fall back to server insertion order | `store.py:130-135` |
| §2.4 | insert | ambiguity | `created_at`/`updated_at`/`api_request_timestamp` come from real server time, not the logical clock | `store.py:46-57,73-84` |
| §2.4 | insert | ambiguity | A request advances a row's `version` by at most one regardless of how many cascade effects touch it | `store.py:95-104` |
| §2.5 r2 | revise | mismatch | "on the manifest-action endpoint" -> manifest-, site- and appointment-action endpoints | `routes_site.py:122`; `routes_appointment.py:184`; `routes_manifest.py:147` |
| §2.5 r3 | insert | ambiguity | 3 uniqueness constraints + 2 lane-interval rules use `ERR_INVALID_REQUEST` but evaluate after rungs 4/5 | `routes_material.py:58-61`; `routes_container.py:46-49`; `routes_manifest.py:67-70`; `routes_staff.py:98-104` |
| §2.5 r9 | insert | ambiguity | Catch-all list of undedicated preconditions -> `ERR_INVALID_STATE_TRANSITION`; §3 narrative order beats the numbered ladder | `routes_event.py:195-234`; `routes_appointment.py:275-278` |
| §2.8 | insert | ambiguity | `posture_override` accepts only `NONE`/`OPEN`; an `OPEN` override with null expiry lifts nothing | `rollups.py:360-372`; `routes_program.py:86` |
| §2.9 | insert | ambiguity | Clock echoed verbatim, unnormalised; all logical-clock stamps carry that same string | `routes_clock.py:19-21`; `store.py:60-62` |
| §3.1 | revise | mismatch | Zero-budget program is `FROZEN` at creation | `rollups.py:345` |
| §3.2 | insert | mismatch | `finding_code` is not stored on the site row; survives only via the suspension cascade's findings | `routes_site.py:124,150`; `cascades.py:25-35` |
| §3.2 | insert | ambiguity | `RETIRE` with a live event -> `ERR_INVALID_STATE_TRANSITION` | `routes_site.py:133-138` |
| §3.3 | insert | ambiguity | `cancel_reason` is optional, recorded null when omitted | `routes_event.py:172` |
| §3.4 | insert | ambiguity | Window-containment and 12h-cap breaches -> `ERR_INVALID_REQUEST`, tested before the safety rules | `routes_staff.py:98-104` |
| §3.4 | insert | ambiguity | `lane_number` is never tested against the site's `lane_count` | `routes_staff.py:88` |
| §3.5 | insert | ambiguity | `VERIFY` accepts only `PENDING_VERIFICATION`/`INELIGIBLE_OUT_OF_JURISDICTION` | `routes_resident.py:89-91` |
| §3.5 | insert | ambiguity | `vehicle_count` is inert — one slot per appointment | `rollups.py:132-134` |
| §3.6 | insert | ambiguity | `remediation_note` accepted but not persisted | `routes_event.py:253` |
| §3.6 | insert | ambiguity | The six containment transitions are exhaustive; PASS-on-`COMPLIANT` and FAIL-on-`DEFICIENT` refused | `routes_event.py:56-63` |
| §3.7 | insert | ambiguity | `no_show_note` accepted but not persisted | `routes_appointment.py:187` |
| §3.8 | insert | ambiguity | `POST /containers/{id}/lines` returns the container, not the line | `routes_container.py:121` |
| §3.8 | insert | mismatch | `invoice_reference` accepted but not persisted (PRD said "recorded") | `routes_manifest.py:149` |

Live checks also confirmed, in passing: duplicate `container_code` -> `ERR_INVALID_REQUEST`; `SEAL` on an empty container -> `ERR_INVALID_STATE_TRANSITION`; lane assignment outside the window -> `ERR_INVALID_REQUEST`; `lane_number: 99` accepted at a site with `lane_count: 3`.

---

**Orchestrator independent verification**: `PRD.md` 482 lines / 103,816 chars vs `PRD_COMPLETED.md` 482 lines / 109,729 chars (+5,913 chars, no line-count drift, so every edit was genuinely in-paragraph). Confirmed 5 top-level sections, §4 table = 44 endpoint rows + 2 header rows, §5 table = 39 error rows + 2 header rows — no truncation introduced by the patch.
