# Worklog — task_1462_carnival_midway_amusement_ride_safety

## Step 1: Create Task Directory — 2026-08-13T09:40:00.000Z

Pre-assigned by pipeline invoker: `tasks/task_1462_carnival_midway_amusement_ride_safety/` with `workspace/` subdirectory already created. No index scan performed; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T11:45:00.000Z

Wrote SCAFFOLD.yaml (16 entities, 13 state machines, 8 calculations, 13 validation rows, 82 endpoints, 53 errors, 6 roles, 3 OCC concurrency rules), SCAFFOLD_DIFFICULTY_DESIGN.yaml (20 instances across all 9 rules), SCAFFOLD_CORNER_DESIGN.yaml (53 instances, 2 excluded_because stubs). scaffold_lint.py: VERDICT clean lint (1370 calls scanned). No sibling task consulted.

## Step 3: Copy Shared Files — 2026-08-13T11:46:19.3428363Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-13T12:05:00.000Z

All contracts pass. The 83 vs 82 row count is just the table separator row — every scaffold path is present. The PRD is complete.

**Output:** `workspace/PRD.md` — 407 lines. (The two forbidden design files were not opened, grepped, or referenced.)

**Sections produced:**
- §1 Introduction (2 paragraphs: program risk context + system scope, including the `/midway` mount and logical-clock determinism)
- §2 Global Specifications, 10 subsections: 2.1 RBAC (with per-role `identity:` translations), 2.2 Response Structure (byte-identical verbatim block, verified by string containment), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending), 2.4 Logical Clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`), 2.5 Common Resource Properties (incl. the `common_fields: false` WeatherObservation exception), 2.6 OCC (all three rules with exact endpoint, field, error ID, and 412), 2.7 Money/Rounding (integer cents, round-half-up placement), 2.8 Collections & Cross-Fair Isolation (all per-collection filter params), 2.9 Parallel Ride Postures and Cascading State, 2.10 Validation Order (all 13 priority families in explicit evaluation order with applies-to scopes)
- §3 Business Logic, 8 lifecycle-grouped subsections (engagement setup → state oversight → staffing → operating day/checklist gate → commerce → queues/cycles → weather/incidents → settlement/teardown)
- §4 Endpoint table: 4 columns only, all 82 endpoints
- §5 Error catalogue: 2 columns only, all 53 error IDs; document ends at §5 with no audit footer

**Hard contract results:**
- Contract 1 (field coverage): PASS — 96/96 entity fields, 58/58 request-body/path identifiers, 30/30 query params present in backticks (verified mechanically with fence-aware extraction; first pass needed a fix because the §2.2 JSON fences flip naive backtick parity)
- Contract 2 (rule coverage): PASS — all 13 validation families with ordering and scopes; 3/3 OCC rules (endpoint + `expected_*_version` + exact error ID, no race framing); every state-machine transition across all 14 machines with preconditions paired to error IDs and all side effects (including depth-3 cascades: cycle-threshold suspension, FATAL/order-shutdown revocation, staff-release shift cancellation, close-gates forfeiture); all 8 calculations (permit fee estimated/final with cap-last ordering, marginal credit tiers with per-unit pre-rounding, 6%/50-cent pre-fee service fee, projected vs recognized settlement with per-sale pro-rata rounding, inspector assignment with 2-hour buffer both directions, FIFO boarding with skip-void, wind sweep with 45/39/3-mph hysteresis and inclusive boundary pins, 3-minor-day escalation); sibling branches rendered symmetrically (approve/deny, PASS/FAIL, both resume guards, both abort sources, three pricing kinds)
- Contract 3 (§3 path purity): PASS — 716 backticked tokens in §3, zero path/method/method+path violations; zero pseudocode operators and zero fuzzy-approximation words document-wide (one "around the limit" phrase was rewritten)

**Scaffold ambiguities resolved (faithfully, without inventing rules):**
1. Checklist creation posture — the transition table pins `CHECKLIST_PHASE` only on submit while the error catalog references "checklist ops"; I rendered creation narratively as a checklist-phase activity and pinned the `ERR_INVALID_DAY_POSTURE` gate explicitly on submit only, preserving countersign's late-clearance path during `OPEN`.
2. Appointment ride/fair cross-reference — the field description requires the ride to belong to `fair_id` but nominates no error; I stated the constraint and routed cross-fair disagreements to `ERR_CROSS_FAIR_REFERENCE` per the referential tier.
3. Redemption-void posture — the transition lists only status preconditions, but the `ERR_INVALID_DAY_POSTURE` catalog entry covers "voids outside OPEN"; I applied the OPEN-posture gate to both sale and redemption voids.
4. The rider-height check at redemption time uses `holder_height_in` recorded on the sale — made explicit so the height source is unambiguous.

## Resume Assessment — 2026-08-13T12:45:00.000Z

Previous run terminated mid-flight. State on resume:
- Steps 1–4 complete (SCAFFOLD.yaml 1358 lines, both design indices, PRD.md 406 lines, INSTRUCTION.md) — all valid, kept.
- Step 5 PARTIAL: test_helpers/ (9 files) + test_suite/ (conftest + 3 files) syntactically valid; 38 tests covering 21 distinct instances, all Design tags valid. But 50 of 71 non-stub design instances (20 difficulty + 51 corner, 2 stubs excluded) have NO test. No worklog entry for Step 5 → interrupted mid-generation, no skip decisions recorded.
- Step 6 NEVER RAN: workspace/implementation/ absent.
- Steps 7–9 never ran.

Resume plan: complete Step 5 (missing 50 instances) concurrently with Step 6 (fresh implementation), then Steps 7–9 as normal.

## Step 6: Generate Implementation — 2026-08-13T13:35:00.000Z

All complete. Final summary:

**Files created** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1462_carnival_midway_amusement_ride_safety/workspace/implementation/`):
- `start.sh` (10 lines), `requirements.txt` (1 line)
- `app.py` (81), `db.py` (134), `errors.py` (70), `response.py` (41), `middleware.py` (79), `validators.py` (96), `helpers.py` (208)
- `services/calculations.py` (161), `services/cascades.py` (148), plus empty `__init__.py` files
- `routes/`: `fairs.py` (165), `rides.py` (213), `inspectors.py` (65), `appointments.py` (159), `permits.py` (119), `staff.py` (71), `certs.py` (77), `days.py` (209), `checklists.py` (166), `cycles.py` (198), `redemptions.py` (127), `products.py` (74), `sales.py` (131), `weather.py` (56), `incidents.py` (140), `shifts.py` (169), `clock.py` (42)
- Total: 3,785 lines across 29 files.

**Endpoint coverage: 82 of 82 PRD endpoints implemented** (verified by enumerating the Flask url_map — 82 `/midway/*` rules matching the PRD §4 table exactly).

**Architecture notes:**
- Modules: `db.py` (in-memory store — plain dicts keyed by id, one per collection, empty at every boot; no disk/SQLite/cache anywhere), `errors.py` (full 49-entry error catalog), `response.py` (envelope), `middleware.py` (auth families 1–3), `validators.py` (shape family 5), `helpers.py` (404 resolution, fair derivation, pagination), `services/calculations.py` (permit_fee, tiered bundle subtotal, service fee, daily settlement, inspector assignment), `services/cascades.py` (shared cascades), and one route module per resource.
- Envelope: `meta.api_request_id` (`req_…`) + `meta.api_request_timestamp`; `response_type` object/array/error; list responses add `limit`/`offset`/`total_count`/`has_more` in meta; error data carries `error_id`/`message`.
- Logical clock: module-global starting at exactly `2026-08-01T00:00:00Z`; `POST /midway/_clock/set_current_utc` (admin-only) sets it, rejecting anything below the startup default with `ERR_INVALID_REQUEST`; all date/timestamp comparisons read it; resource timestamps use 3-fractional-digit ISO UTC; stable ordering via hidden `_seq` tiebreaker (stripped at serialization).
- OCC: `expected_staff_version` (crew-shift create), `expected_fair_version` (permit approve), `expected_checklist_version` (checklist countersign) → 412 with the scaffold's exact error ids.
- Cascade handling: request-scoped deduplicated `touch()` so each cascade-touched entity bumps `version` +1 and refreshes `updated_at` exactly once per request. Implemented: permit-approve licensing, cycle-threshold suspension (depth-3: counter → SUSPENDED → CLOSED + queue void), incident severity ladder (incl. 3-minor-day threshold), order-shutdown revoke cascade, wind sweep (per-ride limits + 45-mph fair closure, hysteresis resume at limit−3 / 39), close-gates (rides close, queues expire, credit forfeiture, projected settlement), reconcile (chronological recognized revenue, per-sale ROUND_HALF_UP pro-rata via `Decimal`, breakage, >1000 flag), staff-release shift cancellation, abort/void credit refunds.
- Validation pipeline follows PRD §2.10 family order (auth → role → entity scoping/ownership → path 404 → shape 400 → body FK 404 → state 409 → safety 422 → uniqueness 409 → constraints 422 → temporal 422 → fiscal 422 → cross-fair 422); unknown/computed body fields rejected.

**Boot verification (manual `bash start.sh` smoke test):** launched on `PORT=10462`, bound `0.0.0.0`, HTTP-ready in ~2s. `GET /midway/fairs` → `{"data":[], "meta":{...,"total_count":0}}` (empty state, correct envelope); `POST /midway/fairs` → 201 with `status:"SETUP"`, `version:1`, `created_at:"2026-08-01T00:00:00.000Z"`; killed; second boot returned `total_count:0` again (zero carry-over). Additionally exercised four scripted scenario batches against the live server: full-season e2e (setup → permit → day → checklist → sales → cycles → suspension cascade → re-license → incidents → settlement with exact cent assertions → teardown → archive), auth/envelope edges, inspector assignment (cap/buffer/cancel-frees-slot), deny loop-back with reinspection surcharge, release cascade, queue boarding/void/abort refunds, weather hysteresis, capacity gates — all passed.

## Step 5: Generate Unit Tests (resumed/completed) — 2026-08-13T14:00:00.000Z

All validation gates pass. Work complete — here is the summary for the worklog.

---

**Audit results:** Existing artifacts OK. All helpers/fixtures referenced by test_01–test_03 resolve (`fixtures.py` re-exports the framework's `get_success_data` and the `*_CLOCK_ISO` constants used as `fx.*` attributes; `api_client.py` already wraps every endpoint, including checklist submit/countersign/reject, crew shifts, certifications, teardown/archive, and the clock). All 38 pre-existing test functions carry exactly one `Design:` tag, and every tag resolves to a real instance in the design YAMLs. No dangling imports; no existing file was modified (only an append-only edit to `test_helpers/fixtures.py`).

**Helpers added (all in `test_helpers/fixtures.py`, existing style):**
- `create_dual_role_supervisor(fair_id, full_name)` — seeds an OPERATOR+SUPERVISOR staff member for the countersign SoD probe.
- `get_staff_member(sup, staff_id)` / `get_shift(sup, shift_id)` — readers for OCC version capture and release-cascade assertions.
- `open_checklist(op, ride_id, day_id, items_total)`, `submit_checklist(op, id, items_passed)`, `countersign_checklist(sup, id)` (fresh-read OCC handshake), `reject_checklist(sup, id, reason)` — checklist lifecycle wrappers.
- `begin_day(ctx)` — create day + clock-to-morning + begin-checklists; `clear_ride(ctx, ride_id)` — open/submit/countersign one checklist; `open_gates(ctx)`.
- `setup_two_ride_permitted_fair(name, ...)` — permitted fair with two licensed rides, op certified THRILL+FAMILY (compound-gate and priority-pair tests).
- `setup_two_open_fairs(name)` — two independent fairs each fully permitted with an OPEN day on the same date, monotonic clock, SoD-correct permit approvers (cross-fair redemption test).

**Tests generated: 61 new tests in 8 new files** (all under `test_suite/`):
- `test_04_checklist_lifecycle.py` (9): checklist rejection loop ×2, license-gated checklist creation ×2, `checklist_double_submit_rejected`, `duplicate_checklist_and_incomplete_submit_errors` (two tests), `checklist_countersigner_same_as_performer_rejected`, `open_gates_compound_gate_requires_every_licensed_ride_countersigned`
- `test_05_cycles_queue_credits.py` (12): cycle-threshold cascade ×2, cycle-threshold boundary ×2, credit conservation ×2, rider-count invariant ×2, `load_time_insufficient_credit_skip_and_void`, `redemption_with_zero_credits_rejected`, `redemption_void_and_load_state_errors_on_running_cycle`, `cycle_empty_inprogress_and_sale_void_blocked_errors`
- `test_06_redemption_restrictions.py` (6): state-beats-safety ×2, safety-beats-fiscal ×2, `rider_height_bounds_are_inclusive`, `cross_fair_redemption_rejected`
- `test_07_settlement_and_teardown.py` (5): settlement projected-vs-recognized ×2, `teardown_blocked_until_days_reconciled`, `fair_full_lifecycle_terminal_lockdown`, `begin_checklists_requires_current_date`
- `test_08_staff_crew_occ.py` (7): crew half-open overlap ×2, `crew_shift_season_window_enforced_per_role`, `staff_release_cascades_cancel_future_shifts_and_locks_identity`, all three OCC instances
- `test_09_operator_gates.py` (7): `certification_expiry_boundary_today_valid_yesterday_expired`, `revoked_certification_blocks_checklist_and_double_revoke_fails`, `annual_cert_must_cover_the_season_at_verify`, `verify_assembly_requires_covering_setup_shift`, `verify_assembly_twice_rejected`, `inspector_cannot_complete_unassigned_appointment_returns_403`, `crew_member_cannot_confirm_others_shift_returns_403`
- `test_10_entity_contracts.py` (12): all 7 entities corners, `ride_initial_state_defaults`, `mutation_visible_immediately_in_response_and_version_increments`, `missing_auth_headers_returns_unauthenticated`, `existence_beats_business_on_unknown_path_id`, `rides_filtered_list_reverse_lookup_by_fair`
- `test_11_rbac_and_scope.py` (3): `ride_operator_cannot_create_ticket_products_returns_403`, `program_admin_cannot_register_rides_returns_403`, `cross_fair_staff_scope_forbidden`

**Instances SKIPPED under the PRD-first filter:** none — all 50 work-list instances have verbatim PRD coverage and uniquely-derivable outcomes. Two judgment notes (no full skips):
1. Version assertions use the captured creation version + relative increments (`v+1` per mutation) instead of absolute values (1/2/3/5), because PRD §2.5 pins "increments by exactly one on every mutation" but never states the initial value; absolute values are not uniquely derivable.
2. In `Corner/errors/redemption_void_and_load_state_errors_on_running_cycle`, the sub-assertion "load while RUNNING → ERR_CYCLE_INVALID_STATE" was omitted (PRD §3.6 names that error for dispatch/complete/abort but never for load on a non-LOADING cycle); the instance's headline claim (voiding a REDEEMED redemption whose cycle left LOADING → ERR_REDEMPTION_NOT_VOIDABLE 409, plus the completion side effects) is fully asserted.

**Final coverage: 71 of 71 non-stub instances have ≥1 test** (all 20 difficulty instances have ≥2; the 2 `excluded_because` corner stubs are correctly untranslated). Verified: AST parse of all 21 files OK; every one of the 99 test functions has exactly one `Design:` tag resolving to a real instance; no tag points at a stub; every test docstring carries a verbatim ≥8-word PRD.md substring; all modules import cleanly under `PYTHONPATH=<task_dir>`; no `skip`/`xfail` markers; no scaffold references in generated code.

## Step 7-9: Test-Fix Diagnostic Loop — 2026-08-13T14:05:00.000Z

**Iteration 1 (8-round parallel sweep):** 81/99 passed in every round; union of 18 failing tests, all deterministic (failed in all 8 rounds — not flakiness). Three root causes:
1. 16 tests (`test_05` ×12, `test_06` ×2, `test_07` ×2) — `NameError: name 'create_cycle_payload' is not defined`. TEST HELPERS BUG: `fixtures.py` used `create_cycle_payload` in `open_cycle` but omitted it from the `from .factories import (...)` block. Fixed by adding the import.
2. `test_09::test_expires_today_valid_expired_yesterday_rejected` — expected `ERR_CERTIFICATION_MISSING` (422), got `ERR_DUPLICATE_CHECKLIST` (409). IMPLEMENTATION BUG: `create_checklist` lacked the §2.10 family-8 safety gate ("checklist creation, submission, and countersignature ... a valid operator certification for the ride's class ... ERR_CERTIFICATION_MISSING"), which must precede the family-9 duplicate-checklist check.
3. `test_09::test_revoked_cert_blocks_checklist_and_double_revoke_fails` — checklist creation succeeded (response_type 'object') after the operator's cert was revoked. Same root cause as #2.

PRD coverage + unique derivability verified for both test_09 assertions (§2.10 family 8 scope line names checklist creation and orders it before family 9; §3.3 "Wherever the program demands a certified operator ... ERR_CERTIFICATION_MISSING"). No tests deleted; no assertions weakened.

**Fixes applied:**
- `test_helpers/fixtures.py` — added `create_cycle_payload` to the factories import (16 tests).
- `workspace/implementation/routes/checklists.py::create_checklist` — inserted the family-8 certification check (`has_valid_certification` → `ERR_CERTIFICATION_MISSING`) between the family-7 posture check and the family-9 duplicate check (2 tests).

**Iteration 2 (8-round parallel sweep after fixes):** all 8 rounds 99/99 passed, 0 failed, 0 errors. `results.1..8.json` all clean. Loop exits.

## Step 7: Run Tests and Iterate — 2026-08-13T14:15:00.000Z

All 8 parallel rounds pass 99/99. The loop exits clean.

## Summary

- **Iterations run:** 2 (initial 8-round sweep → fixes → verification 8-round sweep, all 8 rounds 99/99).

- **Tests deleted:** none. Every failing assertion traced to verbatim PRD coverage with uniquely-derivable outcomes.

- **Fixes applied to `test_helpers/`:**
  - `test_helpers/fixtures.py` — added `create_cycle_payload` to the `from .factories import (...)` block. The `open_cycle` helper (line 280) used it without importing it, producing `NameError` in 16 tests (all of test_05, plus cycle-dependent tests in test_06 and test_07). One-line import fix; the factory itself was already PRD-faithful.

- **Fixes applied to `test_suite/`:** none — both failing test_09 assertions were faithful to PRD (§2.10 family 8 scope explicitly covers "checklist creation" and orders it before family 9 uniqueness; §3.3 pins `ERR_CERTIFICATION_MISSING` for missing/invalid operator certification).

- **Fixes applied to `implementation/`:**
  - `workspace/implementation/routes/checklists.py::create_checklist` — inserted the PRD §2.10 family-8 safety gate: `has_valid_certification(ctx["user_id"], ride["ride_class"])` → `ERR_CERTIFICATION_MISSING` (422), positioned after the family-7 state checks (`ERR_RIDE_NOT_LICENSED`, `ERR_INVALID_DAY_POSTURE`) and before the family-9 `ERR_DUPLICATE_CHECKLIST` check. The endpoint previously had no certification gate at creation at all, which both inverted the family-8/family-9 priority (expired-cert operator got `ERR_DUPLICATE_CHECKLIST` instead of `ERR_CERTIFICATION_MISSING`) and let a revoked-cert operator create a checklist successfully.

Key files: `test_helpers/fixtures.py`, `workspace/implementation/routes/checklists.py`.

## Step 8: Finalize PRD — 2026-08-13T14:25:00.000Z

Done. `PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

**Line counts / delta:** PRD.md 406 lines → PRD_FINALIZED.md 406 lines (0% line delta; both edits are within-line revisions, +32 words total).

**Step 7 diff items disposition:**
- `test_helpers/fixtures.py` import fix — pure fixture bug (missing `create_cycle_payload` import); no PRD silence, no edit.
- `implementation/routes/checklists.py::create_checklist` cert gate — genuine PRD internal tension: §2.10 family 8 scoped "checklist creation", but §3.3's exhaustive-sounding enumeration listed only "checklist submission (§3.4) and cycle operations (§3.6)", and §3.4's creation paragraph never mentioned the gate — which is exactly why the original implementation omitted it. Patched via two edits.

**Changes (one bullet per edit):**
- §3.3 — revise — widened the certified-operator enumeration from "checklist submission (§3.4)" to "checklist creation and submission (§3.4)" — `implementation/routes/checklists.py:54`.
- §3.4 — insert — added the creation-time certification gate: "The opener must also hold a valid operator certification for the ride's `ride_class` (§3.3), else `ERR_CERTIFICATION_MISSING`; per the §2.10 pipeline this safety gate is evaluated after the license and day-posture state checks and before the duplicate-checklist check." — `implementation/routes/checklists.py:48-58` (order: `ERR_RIDE_NOT_LICENSED` → `ERR_INVALID_DAY_POSTURE` → `ERR_CERTIFICATION_MISSING` → `ERR_DUPLICATE_CHECKLIST`).

**Per-edit pre-edit search log:**

*Edit 1 (§3.3):*
- (a) Subject: the set of operations demanding a valid operator certification (`ERR_CERTIFICATION_MISSING` enforcement sites).
- (b) Enumerated: `grep -rn "has_valid_certification\|ERR_CERTIFICATION_MISSING"` across `implementation/` → `helpers.py:79` (validity = `ACTIVE` + `expires_on` ≥ logical today), `routes/checklists.py:54` (create), `routes/checklists.py:115` (submit), `routes/cycles.py:56` (cycle create). Second sweep of all cert logic in `routes/`+`services/` → only `certs.py` issue/revoke (§3.3 already covers) and `rides.py:136` annual-cert (separate §3.1 rule). Countersign (`checklists.py:125-152`) has no cert check — wording deliberately says "creation and submission", not countersignature.
- (c) Widened the enumeration by two words ("creation and"); left "cycle operations (§3.6)" and the released-staff clause verbatim (released staff fail §2.1 scoping before this gate — pre-existing text outside step-7 scope).

*Edit 2 (§3.4):*
- (a) Subject: gate set and ordering at `POST /midway/daily-checklists`.
- (b) Enumerated: full read of `routes/checklists.py::create_checklist` (lines 35-74) — auth → body shape → 404/scoping → license → posture → cert → duplicate → cross-fair, matching §2.10 families 7→8→9→13. Cross-checked the parallel `routes/cycles.py::create_cycle` (same state→cert→uniqueness→cross-fair order, so the pinned ordering generalizes), `submit_checklist` (cert after posture, before items check — untouched by this creation-scoped edit), and `countersign_checklist` (no cert — not mis-described).
- (c) Scoped the ordering claim to "after the license and day-posture state checks and before the duplicate-checklist check" (mirrors impl lines 48-58 exactly) and deferred to §3.3 for the validity definition rather than restating it, avoiding any divergence with `helpers.py:79`.

## Step 9: Complete PRD — 2026-08-13T14:55:00.000Z

All edits are in place. The file grew by exactly 2 lines (one inserted paragraph) and +4,039 chars across 21 surgical edits. Here is the completion report.

## Summary

**Produced:** `workspace/PRD_COMPLETED.md`

**Source vs output:** PRD_FINALIZED.md 406 lines / 68,867 chars → PRD_COMPLETED.md 408 lines / 72,906 chars (char-delta **+4,039**, all inside existing paragraphs except one inserted filter-semantics paragraph in §2.8; no new sections).

**Counts:** 19 ambiguity-pins, 2 mismatch-revisions (21 changes total).

**Changes (one per bullet):**

- §2.3 — revise — ambiguity — pinned invalid `limit`/`offset` (non-integer, out of 1–100, negative offset) → `ERR_INVALID_REQUEST`; `created_at` ties broken by creation order; `total_count` = filtered total before pagination; `has_more` = `offset + returned items < total_count` — implementation/helpers.py:167-192, implementation/response.py:30, implementation/db.py:121-122
- §2.4 — insert — ambiguity — all server timestamps (`created_at`, `updated_at`, `api_request_timestamp`) read the logical clock; naive `to_iso8601` read as UTC; rewinding below the startup default → `ERR_INVALID_REQUEST` — implementation/db.py:35-41, implementation/routes/clock.py:27-28,39-40
- §2.5 — insert — ambiguity — one request mutating a resource through several code paths advances `version` exactly once (per-request touch dedup) — implementation/db.py:95-112
- §2.8 — insert — ambiguity — list endpoints have no primary resource, so §2.1 fair-match scoping does not apply to them; any authenticated caller may list/filter any collection — implementation/routes/rides.py:109-120 (and all list handlers), implementation/middleware.py:66-74
- §2.8 — insert — ambiguity — filters are exact case-sensitive equality; unknown query params ignored; `active` boolean filters accept `true`/`false` case-insensitively, any other value leaves the filter unapplied — implementation/helpers.py:158-164,195-204
- §2.10 family 3 — revise — mismatch — split scoping timing: identity (active inspector / active staff with mapped function) at family 3, but fair-match evaluated only once the primary resource is known (after path resolution on path endpoints → unknown path id yields 404 even for a cross-fair caller; right after shape validation on creates), and ownership checks (appointment inspector, checklist performer, cycle operator, shift assignee) run immediately after path resolution before the body — implementation/middleware.py:33-79, implementation/routes/appointments.py:117-119, implementation/routes/checklists.py:104-106
- §2.10 family 5 — revise — mismatch (+ ambiguity) — moved "wristband sale quantity one" out of pure shape: it is enforced after the product and day references resolve, before the posture check; also pinned required strings non-blank and strict `YYYY-MM-DD` dates, and entity-dependent `OPERATOR`/`CREW` function checks evaluated right after the staff reference resolves — implementation/routes/sales.py:42-43, implementation/routes/certs.py:31-32, implementation/routes/shifts.py:51-52, implementation/validators.py:30-38,72-84
- §2.10 family 7 — insert — ambiguity — the three §2.6 OCC version checks are evaluated immediately after the state precondition, ahead of families 8–13 — implementation/routes/permits.py:71-75, implementation/routes/checklists.py:133-136, implementation/routes/shifts.py:53-56
- §2.10 family 8 — revise — ambiguity — added ride-cycle creation to the safety-family endpoint list (operator-certification gate sits between the ride-OPEN state check and the cycle-in-progress check) — implementation/routes/cycles.py:54-60
- §2.10 family 13 — revise — ambiguity — added the cross-fair pairing checks of appointment, checklist, ride-cycle, incident, and ticket-sale creation to the family-13 endpoint list — implementation/routes/appointments.py:69-70, checklists.py:59-60, cycles.py:61-62, incidents.py:50-51, sales.py:50-51
- §3.2 — insert — ambiguity — inspector ranking ties further broken by earlier registration order (`created_at` ties are the norm under the frozen logical clock) — implementation/services/calculations.py:157
- §3.2 — insert — ambiguity — inspector deactivation is idempotent: already-inactive → success, no version advance — implementation/routes/inspectors.py:62-64
- §3.3 — revise — ambiguity — cert issuance naming a non-`OPERATOR` worker → `ERR_INVALID_REQUEST` — implementation/routes/certs.py:31-32
- §3.3 — revise — ambiguity — shift booking: missing `CREW` function → `ERR_INVALID_REQUEST`; `RELEASED` worker → `ERR_STAFF_INVALID_STATE` — implementation/routes/shifts.py:51-54
- §3.4 — revise — ambiguity — operating-day date outside `[opening_date, closing_date]` or in the past → `ERR_INVALID_REQUEST`, evaluated right after the fair-state check and before the duplicate check (prose reordered to impl order) — implementation/routes/days.py:47-57
- §3.4 — insert — ambiguity — begin-checklists leaves rides whose `minor_incidents_today` is already zero untouched (no version advance) — implementation/routes/days.py:107-110
- §3.5 — revise — ambiguity — product deactivation is idempotent, no version advance when already inactive — implementation/routes/products.py:71-73
- §3.6 — insert — ambiguity — boarding (`/load`) is restricted to the cycle's own operator (`ERR_FORBIDDEN`), requires `LOADING` (`ERR_CYCLE_INVALID_STATE`), and re-checks neither ride `daily_status` nor day posture — implementation/routes/cycles.py:104,107-108
- §3.6 — insert — ambiguity — a boarding call advances the cycle's `version` by one even when no guest boards — implementation/routes/cycles.py:136
- §3.7 — revise — ambiguity — "latest observation of the day" ties on `created_at` broken by insertion order; ride resume targets the fair's latest `OPEN` day by date, none at all → `ERR_INVALID_DAY_POSTURE` — implementation/routes/rides.py:196-213, implementation/routes/days.py:204-209
- §3.7 — insert — ambiguity — ride resume evaluates the hold-state check (`ERR_RIDE_INVALID_STATE`) first, ahead of day-posture, licensure, and the wind/incident guards — implementation/routes/rides.py:172-190

**Notable confirmations (no change needed):** all endpoint roles, field shapes, the permit-fee/tier-pricing/service-fee/settlement math, the suspension/revocation/weather/close-gates cascades, queue ordinals, and every PRD-pinned validation order matched the implementation exactly; tests were used only as auxiliary cross-reference per instructions.
