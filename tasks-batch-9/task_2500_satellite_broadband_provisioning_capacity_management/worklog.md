# Worklog — task_2500_satellite_broadband_provisioning_capacity_management

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2500_satellite_broadband_provisioning_capacity_management` and its `workspace/` subdirectory. Index 2500 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T01:32:00.000Z

Done. All three scaffold artifacts are complete and the linter is green.

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2500_satellite_broadband_provisioning_capacity_management/`): `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`

**SCAFFOLD.yaml (§1.0–§1.7)** — `difficulty_level: expert_plus`, `api_prefix: /satellite-broadband`, clock epoch `2026-08-01T00:00:00Z`. 13 entities, 55 endpoints, 7 state machines (`state_machine_shape: parallel` — Subscription carries service × authorization × priority × disclosure dimensions; RoamingAuthorization cyclic; Terminal cyclic+branching), 7 calculation rules (2 dual-variant: `cell_slot_availability` advertised_strict/admission_expiry_aware and `outage_credit_amount` provisional_event_level/final_daily_prorated), 38 priority-ordered validations, 48 error codes, 3 OCC `concurrency_rules` (activation→ServiceCell, plan-change→Beam, capacity-policy→Beam), 5 roles under `role_model: segregation_of_duties`, `consistency_model: immediate`, complexity layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, archetypes `quota_allocation` + `compliance_audit`. Neither design key present.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — 9 rule_ids / 20 instances (≥2 each): dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — all 9 claim-extraction-guide sections, 97 instances (75 with full `test_recipe`, 22 `excluded_because` stubs delegating to named §1.8 instances): entities 13, state_machines 16, calculations 13, validations 14, endpoints 7, errors 20, rbac 4, cross_cutting_layers 9, consistency_model 1. RBAC covers exclusive-op sufficiency, 8 cross-role `ERR_UNAUTHORIZED` refusals, entity-backed `ERR_NOT_RESOURCE_OWNER` row scoping, and X-User-ID segregation on outage-credit decide. cross_cutting_layers covers one stale-version test per OCC rule plus correct-version success and version-increment monotonicity, a 3-hop suspend cascade (beam SATURATED→NORMAL → cell CLOSED→WAITLIST_ONLY → subscriber SUSPENDED), fair-use threshold reset across a billing-cycle-close, and slot-ledger reconciliation across reserve/waitlist/promote/cancel.

**Verification** — `scaffold_lint.py`: `VERDICT: clean lint` (1283 calls scanned across §1.8+§1.9). All 48 catalogue error codes have an explicit `error_id ==` assertion; zero unbound `${var}` placeholders; zero name collisions across the two design files; no keys outside the sanctioned instance schema. Six HTTP-status assertions were corrected against the catalogue during the final pass (ERR_RESERVATION_EXPIRED ×2, ERR_WAITLIST_CLOSED, ERR_CELL_CAPACITY_EXHAUSTED, ERR_BEAM_SUSPENDED, ERR_BEAM_OVERSUBSCRIBED — all 409, not 422).

## Step 3: Copy shared files — 2026-09-03T01:33:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T01:48:00.000Z

PRD generation for `task_2500_satellite_broadband_provisioning_capacity_management` is complete and verified.

**Output:** `workspace/PRD.md` — **521 lines**, ends at a real section boundary (final row of the §5 error table, `| ERR_BEAM_SUSPENDED | 409 |`).

**Withheld files honoured:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was read, grepped, or referenced. Sole content source was `SCAFFOLD.yaml` (2714 lines, read in full).

**Section list**: §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 API Response Structure verbatim, 2.3 Pagination, 2.4 Logical Clock, 2.5 Common Resource Properties, 2.6 Optimistic Concurrency on the Two Scarce Ledgers, 2.7 Numeric Precision and Rounding, 2.8 The Two Scarce Ledgers: Cell Slots and Beam Megabits, 2.9 Cascade Discipline, 2.10 Regulatory Governance, 2.11 Order of Rejection — full 38-priority ladder with error ID, HTTP status, exhaustive applies_to); §3 Business Logic (3.1 Spectrum Licensing/Coordination/Enforcement, 3.2 Beams/Coverage Cells/Capacity Governance, 3.3 Availability Determination/Reservation Holds/Waitlist, 3.4 Terminal Logistics and Self-Installation, 3.5 Activation/Consumer Disclosure/Network Authorisation, 3.6 Fair-Use Metering/Deprioritisation/Plan Re-Assignment, 3.7 Portability/Roaming/In-Motion Authorisation, 3.8 Performance Impairment/Outage Credits/Subscriber Ledgers, 3.9 Suspension/Termination/Billing-Cycle Ops Run); §4 Endpoint Definitions (55-row table); §5 Error Code Catalogue (48-row table).

**Hard Contract reports**

Field coverage: entities 124/124 fields; request_body 70/70; query_params 30/30; output objects 19/19; error_codes 48/48; roles 5/5; enum values 67/67 → PASS.

Rule coverage: validations 38/38 covered in the §2.11 ordered ladder (relative priority, error ID, HTTP status, full applies_to each); concurrency_rules 3/3 in §2.6 (activation-stale-service-cell → ERR_STALE_SERVICE_CELL_VERSION 412; plan-change-stale-beam and capacity-policy-stale-beam → ERR_STALE_BEAM_VERSION 412; write endpoint, compared field and 412 named for each); transitions 47/47 across 7 machines (SpectrumLicense 7, ServiceOrder 7, Terminal 10, Subscription 13 over 4 parallel dimensions, RoamingAuthorization 6, OutageEvent 1, OutageCredit 3) with guards/preconditions/cascades stated; calculations 7/7 including both variants of cell_slot_availability and outage_credit_amount, plus beam_weighted_oversubscription, fair_use_priority_threshold, cycle_charge_with_overage_discount, waitlist_priority_score, governing_license_selection — every constant embedded in prose, every rounding point and step order pinned; endpoint side effects all covered incl. the 4-hop install cascade, 3-hop RMA cascade, licence suspension fan-out, activation double-ledger debit and 6-step billing-cycle ops run; applies_to scopes enumerated exhaustively; all 124 field semantics/defaults/nullability/precision stated; sibling-branch symmetry maintained on the 3 coordination outcomes, 2 order-determination branches, 3 roaming modes, 2 roaming decisions, 2 credit decisions, 2 return conditions and 2 authorisation targets → PASS.

Path purity (§3 only): 1058 tokens scanned; 0 starting with "/", 0 bare HTTP-method tokens, 0 method+path combined → PASS.

**Coverage confirmation:** all 13 entities, 55 endpoints, 7 state machines (47 transitions), 7 calculation rules (9 variant bodies), 3 concurrency rules, 38 validations and 48 error codes from `SCAFFOLD.yaml` are represented. §2.2 is byte-identical to the fixed response-structure contract. No pseudocode, no operator glyphs, no fuzzy quantifiers.

**Orchestrator truncation check:** independently verified — 521 lines / 110155 bytes; §4 table = 55 endpoint rows + header/separator; §5 table = 48 error rows + header/separator; file ends on a completed table row, not mid-sentence. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T02:22:00.000Z

Stage 2 complete and verified. Final report:

## Files created

**`test_helpers/` (9 files, infrastructure)**
`types.py` (UserRole + ~30 state enums + TypedDicts for all 13 entities), `api_client.py` (`ApiClient` subclassing the framework's `GenericApiClient`, one method per endpoint under `/satellite-broadband`), `api_errors.py` (48-member `ApiErrorId` str-enum + `HTTP_STATUS_CODES` registered via `set_error_http_status_map`), `constants.py`, `test_users.py` (4 opaque operator builders + the mandatory `make_subscriber_headers`), `factories.py` (30 payload factories; `field=None` expresses omission), `assertions.py` (13 entity shape checkers + 5 domain invariant checkers), `fixtures.py` (≈50 primitives + 11 composite setup ladders), `__init__.py` (barrel, 237 exports).

**`test_suite/` (13 files)** — `conftest.py` plus 12 numbered test modules:
`test_01_dual_variant_and_formula_composition` 10, `test_02_parallel_dimensions_and_cascades` 13, `test_03_rejection_order_and_boundaries` 10, `test_04_cross_entity_windows_and_ledgers` 23, `test_05_resource_shapes_and_defaults` 13, `test_06_lifecycle_transitions` 13, `test_07_calculation_rules` 10, `test_08_validation_rules` 13, `test_09_endpoint_behaviours` 8, `test_10_error_catalogue` 12, `test_11_access_control` 5, `test_12_concurrency_and_consistency` 8.

## Test counts

| | instances | tests |
|---|---|---|
| Queue A (Difficulty, §1.8) | 20/20 translated | **56** (every instance ≥2) |
| Queue B (Corner, §1.9) | 75/75 non-stub translated | **82** (every instance ≥1) |
| **Total** | 95 | **138 functions → 172 collected cases** |

The 22 `excluded_because:` stubs were not translated and no placeholders were emitted.

## Instances skipped

**None.** All 20 difficulty and all 75 non-stub corner instances passed the PRD-first two-condition filter. Six individual *assertions* were dropped inside otherwise-kept instances where the PRD is silent: a new cell's `free_slot_count` (see below), an unstamped `promoted_at`, `coordination_note` storage on the REFUSED branch, a re-touch version bump on an already-suspended beam, a Subscriber-role cell read (§2.1's ownership chain has no service-cell entry), and a non-existent `GET /subscribers` collection the design assumed. Empty-field checks assert falsy rather than `None`, since the PRD says "empty" without fixing null vs `""`.

## Verification performed

- **Coverage audit** — every `Design:` tag resolves to a real `name:` in the source yaml with matching rule_id/section; no untagged, dual-tagged, or stub-pointing tests; no `pytest.mark.skip/xfail/skipif` anywhere; no occurrence of "scaffold".
- **PRD-citation pass** — all **472** quoted sentences confirmed as literal substrings of `workspace/PRD.md`. One is a 6-word full sentence (`The licence's version increases by 1.`) supplementing a substantive primary citation in the same docstring.
- All 12 modules import cleanly; `pytest --collect-only` collects 172 items with 0 errors.
- `workspace/implementation/` was never read, listed, or written by me or any generation unit.

## Key findings for the implementation side

1. **PRD contradiction on a new cell's `free_slot_count`.** §3.2 states all four counters "start at 0"; §3.3's formula and the "born `AVAILABLE`" clause imply it equals `max_active_terminals`. Not uniquely derivable, so no test asserts either value at birth — I removed the one agent-emitted `== 4` assertion and relaxed `assert_cell_ledger_invariants` to exempt cells still at `version == 1` with all-zero activity. Post-write cells are still checked against the full derivation.
2. **Two design-yaml literals contradict the PRD and were deliberately not copied**: `capacity_state == "CONSTRAINED"` at ratio 1.0 against limit 2.0 (§2.8 bands that as NORMAL, ≤0.75×limit), and HTTP 422 for `ERR_BEAM_SUSPENDED` (PRD §5 says 409).
3. **`ERR_SERVICE_PLAN_NOT_FOUND` is only reachable as a body reference** — ServicePlan has no GET-by-id endpoint, so it is excluded from the not-found parametrization and tested via the order-creation path instead.
4. **§2.11 ordering was used, not assumed** — both priority-pair instances and the expired-reservation instance assert an exact winning error id only because the numbered list orders the competing checks (positions 10 vs 36, 16 vs 23, 26 vs 38).

*Orchestrator note: Steps 5 and 6 were launched in immediately consecutive messages rather than a single message. `test_suite/` did not yet exist when the Step 6 impl generator started, and Step 6 was additionally given an explicit prohibition on reading `test_helpers/` and `test_suite/`, so the impl generator's isolation from the test artifact was preserved.*

## Step 6: Generate implementation — 2026-09-03T04:15:00.000Z

Implementation complete and boot-verified.

**Files created** in `workspace/implementation/` (22 files, ~4,000 lines of Python):

- `start.sh` (executable; reads `$PORT`, binds `0.0.0.0`, `exec`s in the foreground, installs Flask only when missing), `requirements.txt`, `app.py` (blueprint registration, uniform `before_request` authentication, `ApiError`/404/405/500 envelope handlers, a global-lock WSGI middleware so read-decide-write ledger sequences stay atomic)
- Infrastructure: `clock.py` (logical clock from `2026-08-01T00:00:00Z`, 3-fractional-digit ISO output), `db.py` (13 in-memory dicts, empty on boot, per-request `touch()` dedup so a record hit by several cascade hops advances `version` by exactly 1), `errors.py` (all 48 PRD error ids plus status mapping), `constants.py`, `numeric.py` (Decimal + ROUND_HALF_UP, floor conversions), `response.py`, `validators.py`, `auth.py` (roles + the six ownership chains)
- Domain: `capacity.py` (dual-variant cell admission vs advertised availability, beam weighted-sold/ratio/capacity-state, fair-use flip, waitlist scoring/promotion, lazy reservation expiry), `licensing.py` (four-hop enforcement cascade, reinstatement asymmetry, roaming licence ranking), `billing.py` (provisional single-rounding vs final per-UTC-day credit, pinned cycle-charge order), `accounts.py`, `serialize.py` (all derived figures projected at read time)
- Routes: `routes_regulatory.py` (4), `routes_topology.py` (11, incl. the nine-step billing-cycle-close and the clock endpoint), `routes_retail.py` (6), `routes_hardware.py` (10), `routes_service.py` (10), `routes_roaming.py` (6), `routes_impairment.py` (8)

**Endpoint count:** 55 registered routes, matching the 55 rows of PRD §4 one-for-one (34 POST / 21 GET). Storage is in-memory only; nothing is seeded, and a fresh boot answers `GET /satellite-broadband/beams` with an empty array.

**Boot verification:** launched via `./start.sh` with `PORT=19487`, then driven by two end-to-end scripts — both reported **0 failures** — before the process was killed and the port released. Coverage included: licence filing → coordination → beam/cell/plan → subscriber → order → terminal ship/deliver/scan/install → activation with `expected_service_cell_version` → disclosure ack → `IN_MOTION` authorisation → usage ingest with the inclusive fair-use flip (`effective_rate_mbps` dropping to the deprioritized rate) → plan change and capacity policy under `expected_beam_version` → roaming request/request-info/resubmit/approve and a `PORTABILITY_MOVE` that relocated the subscription → outage event resolve (300 minutes, eligible, 1 credit drafted; provisional 34c, final 34c from the 150/150 midnight split, subscriber pending 34 → balance 34) → billing-cycle close (charge 16,305c, fair-use reset, cycle index advanced) → licence SUSPEND cascade (subscription `DEAUTHORIZED` + `deauthorized_by_license_id`) and REINSTATE returning it to `AUTHORIZED_FIXED` → warranty replacement suspending service and the RMA close-out resuming it on the new terminal → suspend/terminate closing the account → damaged return adding the 15,000c fee → waitlist fill to the cap-3 `ERR_WAITLIST_CLOSED`, priority-score promotion on cancellation, and lazy 72-hour reservation expiry → pagination bounds (400), unknown path/id (404) and role refusal (403).

`pyflakes` reports zero findings across all modules; `__pycache__` was removed and no server process remains running.

## Step 7: Run tests and iterate — 2026-09-03T04:32:00.000Z

All 8 rounds passed on the first sweep. No diagnostic action was required.

## Summary

**Iterations run:** 1 (one full 8-round parallel sweep, all rounds launched concurrently under `setsid nohup` and joined with `wait`; no early exit).

**Tests deleted:** none. No test failed in any round, so STEP 1 (PRD coverage / unique-derivability) was never triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Final per-round figures** (from `workspace/implementation/results.${i}.json`):

| round | passed / total | failed | errors | skipped |
|---|---|---|---|---|
| 1 | 172 / 172 | 0 | 0 | 0 |
| 2 | 172 / 172 | 0 | 0 | 0 |
| 3 | 172 / 172 | 0 | 0 | 0 |
| 4 | 172 / 172 | 0 | 0 | 0 |
| 5 | 172 / 172 | 0 | 0 | 0 |
| 6 | 172 / 172 | 0 | 0 | 0 |
| 7 | 172 / 172 | 0 | 0 | 0 |
| 8 | 172 / 172 | 0 | 0 | 0 |

Notes for the orchestrator:
- Sweep ran `prd-bench-local-run` with `--isolation per-test-server --timeout 120 --test-timeout 30`, no `--api-url` (per-round port claimed from the shared registry — the log confirms 8 distinct ports acquired/released, e.g. 59403, 55499).
- Round wall-clock duration was ~305s each under concurrent host load; all 8 completed normally (no `Terminated` pattern, so no SIGTERM reaping artifact).
- The 8 result files remain at `workspace/implementation/results.1.json` … `results.8.json`, and the runner log at `workspace/sweep.log`.

**Orchestrator independent verification of the Step 7 sweep artifacts** (a known failure mode is a subagent claiming a clean sweep while leaving no `results.*.json` behind): all 8 files exist on disk, ~58 KB each, timestamped 04:29, and each parses to `passed=172 total=172 failed=0 errors=0`. `sweep.log` tails with the runner's own `Results: 172/172 passed, 0 failed, 0 errors, 0 skipped` / `Duration: 304.5s` lines and normal port-registry releases. The clean sweep is real; no re-run needed.

## Step 8: Finalize PRD — 2026-09-03T04:33:00.000Z

**SKIPPED** per the skill's skip condition. Step 7 exited on its first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes — zero iterations beyond the baseline. There is therefore no `<step_7_diff>` to hand off and no Step-7-identified PRD silence to patch, so no subagent was spawned and no `PRD_FINALIZED.md` was written. Step 9 consequently starts from `workspace/PRD.md`.

## Step 9: Complete PRD — 2026-09-03T05:15:00.000Z

**Orchestrator decision (recorded here since there is no user to consult):** Step 9 was run as **three sequential file-partitioned passes** rather than the single subagent the skill's default shape describes. Rationale — the implementation is ~4,000 lines across 22 modules and the PRD is 110 KB; a single subagent asked to walk all of it exhaustively reliably under-covers, and its characteristic failure is emitting a `PRD_COMPLETED.md` byte-identical to its source (i.e. the scan silently never ran). Partitioning by implementation file guarantees every module is actually walked and makes non-coverage detectable per pass. Each pass edited the same `PRD_COMPLETED.md` in place, additively, and was told which files the other passes own so no partition was double-scanned or reverted. All three passes were given the same PRD-vs-impl classification method, the same NO-NEW-MISMATCH pre-edit obligation, and the same prohibition on reading `SCAFFOLD*.yaml` and `worklog.md`.

Source file: `workspace/PRD.md` (Step 8 skipped, so no `PRD_FINALIZED.md`).
Result: `workspace/PRD_COMPLETED.md` — **521 lines / 109,774 chars → 522 lines / 125,943 chars (+16,169 chars)**.
Totals across the three passes: **57 changes = 47 ambiguity-pins + 10 mismatch-revisions** (plus 1 one-word consistency fix in §4). No new sections; all edits in-paragraph or single-bullet.

### Pass A — `routes_regulatory.py`, `routes_topology.py`, `licensing.py`, `capacity.py`

521 → 521 lines, 110,155 → 113,717 chars (+3,562). 14 source lines touched, 18 changes: **15 ambiguity-pins, 3 mismatch-revisions.**

- §2.10 — revise — ambiguity — governing-licence ranking gains a residual tie-break (filing order) after `expires_at` desc / `created_at` asc — `licensing.py:106`
- §3.1 — revise — mismatch — licence `jurisdiction_code` format is "uppercase letters with **at most** a single hyphen" (`USA` is valid), and the format check applies to licences only (every other jurisdiction field is length-checked) — `validators.py:18,60`; `routes_regulatory.py:43`
- §3.1 — insert — ambiguity — `expires_at` accepted as supplied, including an already-past instant — `routes_regulatory.py:46`
- §3.1 — insert — ambiguity — `coordination_note` is 1–500 chars, and an omitting filing empties the field (discarding an earlier note) in all four branches — `routes_regulatory.py:85,94-104`
- §3.1 — insert — ambiguity — a `REFUSED` coordination suspends beams **only**: no deauthorisation, no roaming revocation, no cell re-stamp — `routes_regulatory.py:105`; `licensing.py:18-26`
- §3.1 — insert — ambiguity — enforcement `reason` is 1–500 chars and a reinstatement's reason overwrites `enforcement_reason` — `routes_regulatory.py:121,143`
- §3.1 — insert — ambiguity — a `TERMINATED` subscription is skipped by reinstatement and keeps its `deauthorized_by_license_id` — `licensing.py:72-79`
- §3.2 — insert — ambiguity — `satellite_code` is 1–100 chars — `routes_topology.py:66`
- §3.2 — revise — mismatch — beam creation may declare `deprioritization_grace_gb` (≥0, default 0); PRD had it unconditionally starting at 0 — `routes_topology.py:76`
- §3.2 — insert — ambiguity — a beam born `SUSPENDED` under an uncoordinated licence stays so after a grant; only reinstatement re-activates a beam — `routes_topology.py:95`; `licensing.py:63-70`
- §3.2 — insert — ambiguity — a cell's `jurisdiction_code` is never compared to the licence's — `routes_topology.py:276`
- §3.2 — revise — mismatch — **the known PRD self-contradiction, resolved**: only `committed_terminal_count`, `reserved_slot_count`, `waitlist_depth` start at 0; `free_slot_count` starts equal to `max_active_terminals` (so a new cell is born `AVAILABLE`) — `capacity.py:116-123`
- §3.2 — insert — ambiguity — cell reads/list/availability carry no ownership check (no subscriber chain) — `routes_topology.py:299-345`
- §3.2 — insert — ambiguity — policy-write fields are both mandatory, limit bounded 1.0–20.0, grace ≥0; no congestion precondition (a limit leaving the beam `SATURATED` is admitted) — `routes_topology.py:138-139`
- §3.2 — revise — ambiguity — the policy re-evaluation walks every subscription in `created_at` order regardless of `service_state` — `routes_topology.py:150`; `capacity.py:58`
- §3.3 — insert — ambiguity — waiting days floored at 0 when the clock was moved back behind `created_at` — `capacity.py:272-273`
- §3.3 — revise — ambiguity — promotion uses the **strict advertised** free-slot figure (an expired-but-unswept hold blocks promotion), residual tie-break by filing order, is **not** gated on `availability_state`, and re-scoring without promotion bumps neither `updated_at` nor `version` — `capacity.py:277-306`
- §3.9 — insert — ambiguity — sweep orders: subscriptions `created_at` asc, cells `cell_code` asc, orders within a cell `created_at` asc — `routes_topology.py:179-207,244-251`
- §3.9 — insert — ambiguity — the beam's `version` moves once per ops run (step 1 already moved the record) — `routes_topology.py:166,242`; `db.py:85-93`
- §3.9 — revise — ambiguity — `charged_subscription_count` counts those actually charged; `restored_subscription_count` counts only `DEPRIORITIZED → PRIORITY` flips, not every reset; `promoted_order_count` totals across cells — `routes_topology.py:226,238,247`

Pass A NO-NEW-MISMATCH log: **Jurisdiction format** — enumerated all `req_jurisdiction` callsites (regulatory strict; topology cell, retail subscriber, roaming target non-strict) → scoped the format claim to licences, "length only" elsewhere. **`coordination_note`** — all four branches assign the possibly-`None` note → wording made branch-universal. **Refusal cascade** — compared `suspend_beams_of_license` against `enforcement_cascade`/`expire_license` → claim restricted to the refusal path; noted derived `CLOSED` without version movement rather than "cells recompute". **Beam re-activation** — grepped every `beam_state` assignment (create, suspend cascade, reinstate cascade only) → "only a licence reinstatement does" is exhaustive. **`free_slot_count` at birth** — checked `free_slot_count`, `admission_free`, `availability_state`, `serialize.service_cell` → phrased as the derived difference, so `max_active_terminals` 0 still yields 0/`CLOSED`. **Promotion routine** — enumerated all four `run_promotion` callsites (cancel, terminate, portability approve, cycle close) plus `free_slot_count` vs `admission_free` → strict-figure / no-availability-gate / no-version-bump-on-rescore hold at every callsite; `expire_reservations`' "never promotes" rule left untouched. **Policy re-evaluation** — checked `apply_fair_use_threshold`'s other callers (usage ingest, plan change) → the "regardless of `service_state`" wording confined to the policy-write sentence. **Beam version once per run** — verified `touch()`'s per-request dedupe; claim kept local to the ops run. **Cell-read ownership** — `auth.py` wiring belongs to Pass C, so the exception was stated only for cell endpoints rather than weakening §2.1/§2.11 #3; explicitly deferred to Pass C.

### Pass B — `routes_retail.py`, `routes_hardware.py`, `routes_service.py`, `accounts.py`

521 lines / 113,717 → 521 lines / 118,320 chars. All edits in-paragraph. 21 changes: **19 ambiguity-pins, 2 mismatch-revisions.** Pass A's 18 edits left intact; `PRD.md` untouched.

- §2.1 — insert — ambiguity — collection endpoints apply no ownership narrowing for a `Subscriber` caller (they see every matching row and must use filters); nested collections check the path parent — `routes_retail.py:143`, `routes_hardware.py:89`, `routes_service.py:161` vs `routes_hardware.py:173`, `routes_service.py:435`
- §2.11 item 5 — revise — **mismatch** — the universal "path id before body reference" claim now records the one deviation: transfer resolves `new_subscriber_id` before its path terminal id, so a doubly-unknown transfer reports `ERR_SUBSCRIBER_NOT_FOUND` — `routes_hardware.py:350-353`
- §2.11 item 11 — revise — **mismatch** — plan change requires `PENDING_ACTIVATION`/`ACTIVE` (PRD said "other than `TERMINATED`", contradicting its own §3.6); suspension added; authorisation's live-`service_state` requirement added; disclosure ack's non-`TERMINATED` requirement added — `routes_service.py:293,328,227,198,400`
- §2.3 — insert — ambiguity — residual tie-breaks for the two non-default collections: scans newest-written-first, usage in write order — `routes_hardware.py:178`, `routes_service.py:444`
- §3.3 lazy expiry — insert — ambiguity — sweep runs only after the filing clears its rejections (a refused filing records no expiry and leaves the cell unmoved); cell `version` advances by exactly 1 for the filing as a whole — `routes_retail.py:96-105`, `capacity.py:309-324`, `db.py:71`
- §3.3 filing — insert — ambiguity — filing makes no jurisdiction comparison; the mismatch surfaces only at activation — `routes_retail.py:77-133` vs `routes_service.py:87`
- §3.3 account creation — insert — ambiguity — `email` 1–200 with at-sign, `full_name` 1–200, `jurisdiction_code` 2–8 length-checked only — `routes_retail.py:46-48`
- §3.3 Branch B — insert — ambiguity — the account moves to `WAITLISTED` only from `PROSPECT`; any other state is left alone — `routes_retail.py:128-130`
- §3.3 cancellation — insert — ambiguity — `cancel_reason` 1–500 chars — `routes_retail.py:173`
- §3.4 shipment — insert — ambiguity — `warranty_expires_at` (and `replacement_warranty_expires_at`) accepted as supplied even if already past; liveness tested only at warranty replacement — `routes_hardware.py:59,294,303`
- §3.4 survey — insert — ambiguity — recording a survey stamps the terminal row (`updated_at`, `version` +1) without moving `terminal_state` — `routes_hardware.py:166`
- §3.4 `last_scan_verdict` — insert — ambiguity — ties on the newest `scanned_at` resolve to the last-written survey — `serialize.py:166-167`
- §3.4 RMA close-out hop two/three — revise — ambiguity — *every* `SUSPENDED` subscription on the replaced unit resumes, in `created_at` order, whatever its `suspension_reason`; account only moves if it was `SUSPENDED`; hop three re-scoped to "each resumed subscription's beam" — `routes_hardware.py:233-246`, `accounts.py:39-43`
- §3.4 RMA suspension hop one — revise — ambiguity — applies to every `PENDING_ACTIVATION`/`ACTIVE` subscription on the faulty unit, in `created_at` order — `routes_hardware.py:326-331`
- §3.4 RMA suspension — insert — ambiguity — the previously-unlisted fourth effect: the account settles to `SUSPENDED` per §3.9's rule — `routes_hardware.py:335-337`, `accounts.py:26-36`
- §3.4 returns — insert — ambiguity — a `condition` sent with `INITIATE` is accepted and ignored; `return_condition` stays empty — `routes_hardware.py:255-268`
- §3.5 disclosure ack — insert — ambiguity — `acknowledged_version` 1–20 chars, so an over-long string is 400 not 422 — `routes_service.py:195`
- §3.6 usage ingest — insert — ambiguity — an uncounted reading does not mutate the subscription row at all — `routes_service.py:419-423`
- §3.9 suspension — insert — ambiguity — `suspend_reason` 1–500 chars — `routes_service.py:325`
- §3.9 suspension — insert — ambiguity — `authorization_state`, `priority_state` and `disclosure_ack_state` are untouched by suspension — `routes_service.py:334-341`
- §3.9 termination — insert — ambiguity — `termination_reason` 1–500 chars and retained in no field — `routes_service.py:350-351`, `serialize.py:203-229`
- §3.9 termination — insert — ambiguity — termination only ever writes `CLOSED`; an account left holding suspended subscriptions is not re-settled to `SUSPENDED` — `accounts.py:46-56`

Pass B NO-NEW-MISMATCH log: **Collection ownership** — enumerated every `@roles(... "Subscriber")` GET; `list_orders`/`list_terminals`/`list_subscriptions`/`list_roaming`/`list_credits` do no ownership call, `list_scans`/`list_usage` do (`own_terminal`/`own_subscription`); wording split accordingly and deliberately omits service-cells (already pinned by Pass A). **Transfer 404 order** — checked every endpoint holding both a path id and a body FK: `plan-change` resolves path subscription first (`routes_service.py:282-285`), `warranty-replacement` has no body FK, `POST /subscriptions` and `POST /roaming-authorizations` have no path id → transfer is the sole deviation, exception scoped to it. **Item 11** — cross-checked all six endpoints against impl and against §3.5/§3.6/§3.9 prose; kept `terminate` as "non-terminal" and usage ingest deliberately looser (`SUSPENDED` ingest is legal). **Ordering tie-breaks** — verified both sort keys end in the insertion counter and no other collection deviates from `created_at` asc (`db.ordered`, `serialize.default_order`). **Lazy expiry / version-by-1** — traced `expire_reservations` (only in-partition callsite is `file_order`; cycle-close sweep is Pass A's step 4) plus `db.touch` per-request dedup; worded "for the filing as a whole", Pass A's step-7 sentence untouched. **Branch B account state** — enumerated all `account_state` writers (`routes_retail` file/cancel, `capacity.run_promotion`, `accounts.py`); wording avoids claiming anything about `WAITLISTED → WAITLISTED` no-ops. **RMA hops** — both loops iterate `capacity.ordered_subscriptions_on_terminal`; softened hop three to "each resumed subscription's beam"; account hop phrased by reference to §3.9 rather than restating a stronger rule. **Warranty date** — confirmed no validation at ship or at replacement creation and that the only liveness test reads the *faulty* unit's field; both fields named explicitly. **Suspension leaves other dimensions** — verified `suspend` writes only `service_state`/`suspension_reason`, and `DEAUTHORIZED` on a suspended row arrives from the licence cascade or termination → no contradiction with §3.1. **Termination writes only CLOSED** — verified `settle_after_termination` has the single `CLOSED` branch and `settle_after_suspension` is never invoked from `terminate`.

### Pass C — `routes_roaming.py`, `routes_impairment.py`, `billing.py`, `serialize.py`, `auth.py`, `validators.py`, `clock.py`, `db.py`, `numeric.py`, `response.py`, `errors.py`, `constants.py`, `app.py` + the global contract sections

521 lines / 118,320 → 522 lines / 126,422 bytes (125,943 chars). 28 `Edit` calls → **23 ambiguity-pins, 5 mismatch-revisions** plus 1 one-word consistency fix in §4.

- §2.1 — insert — ambiguity — `X-User-Role` compared exact/case-sensitively; auth runs before routing so 401 precedes 404 on unknown paths — `auth.py:31-58`, `app.py:61-64`
- §2.1 — revise — mismatch — ownership band narrowed: roaming target read from the *body*'s `subscription_id`; an unresolvable target skips the check (404 wins); coverage cells carry no subscriber chain — `auth.py:84-96`, `routes_roaming.py:87-89`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → 400 (never clamped); `offset` past the end returns an empty page with the true `total_count` — `validators.py:196-214`, `response.py:38-47`
- §2.3 — insert — ambiguity — enum filters 400 on an unknown member, id/code filters accept any string and simply match nothing; multiple filters conjunctive; unknown query params ignored — `validators.py:217-233`
- §2.3 — insert — ambiguity — equal `created_at` breaks to insertion order; `id` is never an ordering key — `db.py:63-66`
- §2.4 — insert — ambiguity — `api_request_timestamp` is the logical clock, not wall time — `response.py:14-21`
- §2.4 — insert — ambiguity — the clock endpoint returns `current_utc` only and accepts backward moves — `routes_topology.py:388-397`, `clock.py:30-33`
- §2.4 — insert — ambiguity — `Z`/offset/naive ISO inputs all normalise to UTC; unparseable → 400 — `clock.py:36-52`
- §2.5 — insert — ambiguity — empty optional fields render as JSON `null`; enumerated the read-time projections (cell counters, beam congestion, ledgers, `effective_rate_mbps`, `last_scan_verdict`) — `serialize.py`, `capacity.py`
- §2.5 — revise — **mismatch** — `version` rises by 1 **per request**, not per mutation: repeated touches inside one request collapse — `db.py:47-60`
- §2.7 — insert — ambiguity — new final bullet: integral decimals render as bare integers, no trailing zeros — `numeric.py:39-45`
- §2.11 item 3 — revise — **mismatch** — ownership band scope (unresolvable target / no-chain cell pass untouched) — `auth.py:84-96`
- §2.11 item 4 — insert — ambiguity — body-shape rules (non-object → 400, absent body = `{}`, unknown fields ignored except roaming's `target_service_cell_id`) — `validators.py:20-33`, `routes_roaming.py:96-102`
- §2.11 item 4 — revise — **mismatch** — the two `ended_at` cross-field rules are evaluated after the position-5 path-id lookup — `routes_impairment.py:154-163`
- §2.11 items 19 & 20 — revise — **mismatch** — `ERR_LICENSE_NOT_ACTIVE`/`ERR_SPECTRUM_NOT_COORDINATED` are reachable only from `.../authorize`; a roaming decision reports the empty-candidate error at position 23 — `licensing.py` candidate filter, `routes_roaming.py:279-286`
- §5 preamble — insert — ambiguity — three out-of-catalogue transport ids (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500) named in prose, table left at 48 rows — `app.py:70-95`
- §3.7 request — insert — ambiguity — the window is never compared to the clock; only `TERMINATED` is refused; no licence consulted until the decision — `routes_roaming.py:103-136`
- §3.7 review ×2 — insert — ambiguity — `info_request_note` required, 1..1000; resubmission rewinds neither `info_round_count` nor the stored note — `routes_roaming.py:204,222-241`
- §3.7 decide ×2 — insert — ambiguity — `decision_note` optional, 1..1000, replaced (or cleared) on every decision call — `routes_roaming.py:249,257,310`
- §3.7 denial — insert — ambiguity — a `DENY` runs none of the approval gates — `routes_roaming.py:255-259`
- §3.7 approval — revise — **mismatch** — dropped the two unreachable licence errors; gate is TERMINATED-only; the beam checked is the subscription's *current* cell's beam, not the target's — `routes_roaming.py:264-307`
- §3.7 IN_MOTION bullet — insert — ambiguity — the lift applies only from `AUTHORIZED_FIXED`; any other state is left alone — `routes_roaming.py:314-317`
- §3.8 open — insert — ambiguity — `started_at` is never compared to the clock — `routes_impairment.py:64-84`
- §3.8 decide — insert — ambiguity — `decision_reason` optional, 1..1000 — `routes_impairment.py:264`
- §3.8 ledger — insert — ambiguity — the subscriber row is stamped on resolution and on decision, not on submission — `routes_impairment.py:200-203,252-256,291-296`
- §4 row 422 — revise — consistency — "persisted slot ledger" → "live slot ledger", so the row does not contradict the new §2.5 projection sentence

Pass C NO-NEW-MISMATCH log: for every edit the sibling callsites were enumerated first, including Pass A's and Pass B's files — `sort`/`sorted` swept across all of `implementation/` to prove no path orders by `id`; every `filter_enum`/`filter_value` call in all seven route modules checked before the §2.3 filter sentence; every `touch(subscriber)` site checked before the §3.8 ledger sentence; a token scan of §3.7/§3.8 against `serialize.py` confirmed no PRD-named field is missing and no serialized key is unnamed in the PRD; the §2.5 projection list cross-checked against `capacity.py`/`licensing.py` so the wording stays true there too. Where impl was non-uniform, under-determined wording was used instead of a universal claim (e.g. §2.11 item 3's "a target that resolves to nothing … pass this band untouched"; §2.5's projection list enumerated rather than generalised). Tests were consulted only as cross-reference — notably to confirm nothing exercises the three transport error ids, so pinning them in prose is safe.

Pass C integrity verification: `differs from PRD.md: True` · `§2.2 byte-identical: True` · `§4 endpoint rows: 55` · `§5 error rows: 48` · last line `| ERR_BEAM_SUSPENDED | 409 |` with trailing newline · `malformed table rows: []` · code fences balanced (4) · no unbalanced inline backticks · all 48 table statuses match `errors.py`. File ends at a real section boundary.

### Orchestrator independent verification of Step 9

- `PRD_COMPLETED.md` exists: 522 lines / 126,422 bytes vs `PRD.md` 521 lines / 110,155 bytes; `cmp` reports the two files **differ** (so the scan genuinely ran — the byte-identical no-op failure mode did not occur).
- `PRD_FINALIZED.md` correctly absent (Step 8 skipped).
- §4 endpoint table = 55 rows, §5 error table = 48 rows, 28 headings, file ends on the completed final error row. Not truncated.
- `find -newermt '2026-09-03 04:30'` over `implementation/`, `test_suite/` and `test_helpers/` returns **nothing**: Step 9 edited only the PRD, so the 8-round 172/172 green sweep from 04:29 still describes the delivered code. `__pycache__` directories removed.

**PIPELINE COMPLETE.** Step 9 has written `workspace/PRD_COMPLETED.md`.
