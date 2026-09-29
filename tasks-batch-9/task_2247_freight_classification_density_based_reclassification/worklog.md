# Worklog — task_2247_freight_classification_density_based_reclassification

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2247_freight_classification_density_based_reclassification/` and `workspace/` subdirectory (directory name pre-allocated by the caller).

## Step 2: Generate scaffold — 2026-09-01T12:35:28.000Z

All three scaffold artifacts are complete and `scaffold_lint.py` reports **clean lint** (1049 calls scanned, all conforming to §1.5; all FKs reverse-reachable).

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2247_freight_classification_density_based_reclassification/`):

- **SCAFFOLD.yaml** (2952 lines, §1.0–§1.7, no design keys)
  - 14 entities: Terminal, Customer, TariffVersion, CommodityProfile, RateProgram, ExceptionAgreement, Shipment, ShipmentLine, CaptureEvent, InspectionFinding, CorrectionNotice, Dispute, CreditMemo, RepricingRun
  - 11 state machines (parallel shape: shipment `class_status` × `billing_status`, notice lifecycle with VOID/supersede, dispute cycle with supplement rounds, tariff/program/exception/finding/repricing lifecycles)
  - 9 calculations (two-step cube/density rounding → density bracket; class resolution via constraint propagation with exception/FAK override then characteristic floor; shipment charge with aggregate weight break + min charge; notice delta with TERMINAL_PROVISIONAL vs AUDIT_FINAL variants; liability index rolling-vs-lifetime decay; two-pass migration impact model; dispute-window interval merge; credit waterfall with capped interest outside the ledger identity; capture variance gate)
  - 56 endpoints, 51 errors, 18 validations (explicit priority ladder), 6 roles (2 entity-backed), 3 concurrency rules, complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; role_model segregation_of_duties; consistency immediate
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1960 lines) — single key `scaffold_difficulty_design`: **9 difficulty rules × 2 instances = 18 instances** (variant divergence, ordering/rounding traps, parallel + cyclic state machines, cascade and compensating cascade, validation-priority conflicts, boundary values, cross-entity blocking preconditions, interval/adjacency and buffer windows, money and count invariants)
- **SCAFFOLD_CORNER_DESIGN.yaml** (4327 lines) — single key `scaffold_corner_design`: **all 9 guide sections**, 79 instances = 52 full test recipes + 27 `excluded_because` stubs (each citing an existing §1.8 instance by name): entities 11, state_machines 12, calculations 15, validations 8, endpoints 6, errors 13, rbac 6, complexity_layers 6, consistency_model 2

Verification done beyond the linter: every `claim_type` matches an exact claim-extraction-guide row; all 79+18 instance names unique across both files; no stub carries a `test_recipe` and every cited `difficulty_instance` resolves; all money/rounding asserts are pre-computed literals (e.g. cube 213.33 → density 1.88 → line 9937 floored to 12500; capture 520 lb → variance 30.00% → final delta 28314 + fee 4500 → assessed 45314; 500 lb fixture 15698 with reweigh gate legs at 1.80%/9 lb, 2.00%/10 lb → delta 313, 2.50%/5 lb); banned concurrency vocabulary removed.

## Step 3: Copy shared files — 2026-09-01T12:35:28.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T12:50:00.000Z

PRD generated and audited. All three Hard Contracts pass.

**Output:** `workspace/PRD.md` — 442 lines.

**Structure** (10 §2 subsections, 10 §3 subsections, both domain-derived; §2.2 pasted verbatim from `section-2.2-response-structure.md`):

- §1 Introduction (3 paragraphs)
- §2: 2.1 Authentication, Roles and Acting Identity · 2.2 API Response Structure · 2.3 Pagination and List Filtering · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Validation Ordering and Identifier Resolution · 2.6 Stale-Read Protection on Account and Shipment Writes · 2.7 Rounding Discipline for Cube, Density, Money and Ratios · 2.8 Segregation of Duties and Evidence Sufficiency · 2.9 The Shipment Ledger Identity · 2.10 Cascade Semantics Across the Terminal, Billing and Account Aggregates
- §3: 3.1 Publishing a Classification Standard and its Commodity Catalogue · 3.2 Shipper Accounts, Pricing Programs and Negotiated Exceptions · 3.3 Modelling a Migration and Repricing the Contract Book · 3.4 Tendering a Bill of Lading and Billing it as Declared · 3.5 Measurement at the Dock: Dimensioner and Scale Capture · 3.6 Inspector Findings and their Acceptance · 3.7 Drafting, Pricing and Issuing a Correction Notice · 3.8 The Repeat-Offender Record: Strikes, Liability Indices, Tiers and Education · 3.9 Disputing a Notice: Supplement Rounds and Resolution Outcomes · 3.10 Sweeping Unchallenged Notices and Closing the Shipment
- §4 Endpoint Definitions — 4-column table, 56 rows (exact method/path/role-set match against the scaffold, 0 missing, 0 extra), preceded by the 201/200 status-code paragraph
- §5 Error Code Catalogue — 2-column table, 51 rows, every HTTP status matching the scaffold catalogue

Field coverage check: entities 169/169 present, request bodies 133/133, path params 1/1 — PASS.
Rule coverage check: 18/18 validations, 3/3 OCC rules, 55/55 transitions, 9/9 calculations, 51/51 error ids, 56/56 endpoint side-effect sets, 169/169 structured field contents, 10/10 sibling-branch symmetry groups — PASS.
Path purity check (§3 only): 814 backtick tokens scanned, 0 paths, 0 bare HTTP methods, 0 method+path tokens — PASS.

Additional checks: §2.2 byte-identical to the fixed source; no pseudocode operators anywhere in §3; no fuzzy quantifiers. The two withheld design files were never opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-09-01T13:58:00.000Z

All checks pass. Generation and auditing are complete.

### Files written

**Stage 1 — `test_helpers/` (9 modules)**
`__init__.py` (barrel), `api_client.py` (one method per PRD §4 endpoint + module-level `api_client`), `api_errors.py` (51 error ids + HTTP status map), `constants.py`, `test_users.py` (6 roles + 9 header builders), `factories.py`, `assertions.py` (24 shape assertions), `fixtures.py` (748 lines of scenario composites), plus `test_suite/conftest.py`.

**Stage 2 — `test_suite/` (17 modules, 103 tests)**
- Queue A (difficulty), 52 tests: `test_01_charge_and_density_boundaries.py` (8), `test_02_dock_capture_cascade.py` (6), `test_03_dual_variant_calculations.py` (6), `test_04_shipment_axes_and_overturn.py` (6), `test_05_dispute_rounds_and_education_hold.py` (6), `test_06_validation_priority_order.py` (6), `test_07_interval_overlap_windows.py` (5), `test_08_conserved_ledger_and_counts.py` (6), `test_09_migration_impact_model.py` (3).
- Queue B (corner), 51 tests: `test_10_resource_shapes_and_reads.py` (10), `test_11_lifecycle_transitions.py` (8), `test_12_rating_and_classification_calculations.py` (7), `test_13_validation_gates.py` (5), `test_14_endpoint_surface.py` (5), `test_15_error_surface.py` (5), `test_16_role_and_ownership_boundaries.py` (5), `test_17_version_guards_and_immediate_visibility.py` (6).

### Instances translated vs skipped

- Queue A: 18/18 non-stub instances, every one with ≥2 tests.
- Queue B: 51/52 non-stub instances, each with exactly 1 test. Section spread: entities 11, state_machines 8, calculations 7, validations 5, endpoints 5, errors 5, rbac 5, complexity_layers 4, consistency_model 2.
- 27 `excluded_because:` stubs correctly left untranslated.
- **One skip:** `Corner/entities/customer_system_fields_input_ignored` — the PRD never states that client-supplied system fields are silently ignored, and a faithful implementer could instead reject the write with `ERR_INVALID_REQUEST` under §2.5 step 6, so the asserted outcome is not uniquely derivable. Per the PRD-first filter the gap was left as a gap.

### Audit results

- **Coverage/tags:** 103 tests, 103 `Design:` tags, 0 untagged, 0 dual-tagged, 0 tags resolving to a stub or non-existent instance.
- **PRD citations:** 103/103 quoted spans found verbatim in `workspace/PRD.md`, all ≥8 words and full sentences; no "scaffold", no `§1.` refs, no `skip(`/`xfail`/TODO anywhere.
- **Compile/import/symbol:** `ALL_COMPILE_OK`; all 17 modules import with `PYTHONPATH=.`; zero missing `api_client` methods, `fixtures` attributes, `factories` functions, `test_helpers` exports, or `ApiErrorId` members.

Notable adjudications where the design yaml conflicted with the PRD (PRD won, without weakening any assertion): `class_source` → the PRD's `classification_source`; posture target `NORMAL` → `OPEN`; post-issuance `class_status` `RECLASS_PENDING` → `RECLASSED`; dropped assertions on the PRD-less fields `active_rate_program_id`, `retired_at`, `superseded_by_notice_id`. Every money and geometry literal asserted was recomputed independently from PRD §2.

## Step 6: Generate implementation — 2026-09-01T14:49:00.000Z

Implementation complete and smoke-verified.

### Files written
23 files, ~3.9k lines of Python, in-memory dicts only, zero seed data, no disk/SQLite/tmp state:

- **Launcher / deps**: `start.sh` (executable, SKILL.md template verbatim, binds `0.0.0.0`, `PORT` default 10000), `requirements.txt` (`Flask==3.1.3`)
- **Kernel**: `app.py` (blueprint registration, per-request `RLock` serialization + `g._touched` version-bump guard, `ApiError`/404/405/`HTTPException`/`Exception` handlers all emitting the error envelope), `clock.py` (logical clock pinned to `2026-08-01T00:00:00Z` on every boot), `constants.py`, `util.py` (`Decimal` + ROUND_HALF_UP helpers), `errors.py` (all 51 error ids → HTTP status), `db.py`, `response.py` (meta/envelope, `has_more`), `serialize.py`, `auth.py`, `validation.py`
- **Services** (`services/`): `rating.py` (two-step cube→density, `density_bracket`, 3-step class resolution, `shipment_charge` DECLARED/RECLASSED/MODELED, provisional vs final delta), `customers.py` (strike count, rolling/lifetime liability index, tier, window, education), `notices.py`, `modeling.py` (2-pass migration model)
- **Routes** (`routes/`): `_helpers.py`, `core.py`, `pricing.py`, `shipments.py`, `captures.py`, `corrections.py`, `repricing.py`

### Endpoints
**56 implemented** — set-exact match against the SCAFFOLD's 56 declared method+path pairs (url_map diff empty both directions).

### Verification
Two throwaway smoke scripts (in `/tmp`) drive ~120 calls each over the full lifecycle on freshly booted `start.sh` processes; both pass. Hand-checked money against the SCAFFOLD formulas: per-line vs aggregate weight breaks, provisional (10764) vs final (9360) delta divergence, floor-after-override, fee 4500/2500, deadline = issued + window + 7×supplements, PARTIAL freight credit 12902 + capped interest, full-overturn ledger returning `assessed_total` to `original_charge_cents` with interest outside the identity, rolling index decay (1.2 → TIER_1 → 25-day window) vs undecayed lifetime (1.5), 2-pass volume-tier model (93924, delta −0.088 → HOLD_CLASS_BASED).

One real bug found and fixed during smoke: `rating.line_mode` treated a weight-only (SCALE) capture as mode MEASURED, so under a FAK program/FIXED_CLASS profile the override leaked into `found_class_code` and spuriously set `triggered_reclass`. `line_mode` now requires a non-null `measured_density_pcf` for MEASURED.

### PRD ambiguities resolved by choosing an interpretation
- `api_request_timestamp` is read from the logical clock, not wall time.
- `found_class_code` is the full mode-MEASURED/INSPECTED resolution (override + floor applied) and stays **null** when a capture supplies weight only — a SCALE capture can raise a REWEIGH notice but never a reclass.
- Duplicate `Terminal.code` / `Customer.account_code` → `ERR_INVALID_REQUEST` 400.
- Publish with zero commodity profiles → `ERR_INVALID_STATE_TRANSITION`; a `supersedes_notice_id` belonging to another shipment → also `ERR_INVALID_STATE_TRANSITION`.
- Capture on a zero-line shipment → `ERR_LINE_NO_MISMATCH` (422), evaluated before `ERR_OPEN_NOTICE_EXISTS`; the capture is projected onto mutation-free line drafts so an open-notice rejection leaves no side effects.
- `CaptureEvent.triggered_reweigh` is true only on a false→true flip of `Shipment.reweigh_required`.
- `ERR_NO_RECLASS_BASIS` read literally as (a capture on this shipment) OR (any accepted finding on its lines).
- Line creation recomputes **every** sibling line's `line_charge_cents` (aggregate weight break).
- `close` accepts only `class_status ∈ {DECLARED, CAPTURED, RECLASSED}` and refuses while any notice is open; billing a non-UNBILLED shipment is always `ERR_SHIPMENT_ALREADY_BILLED`; tender distinguishes `ERR_CUSTOMER_CLOSED` from `ERR_CUSTOMER_CREDIT_HOLD`.
- `line_measurements[]` dimensions are all-or-none per element.
- Repricing `model` applies the run's sample window; `commit` re-pins each scoped ACTIVE program and recomputes its canonical window-free model.
- `version` is bumped at most once per row per request regardless of cascade depth.
- Shipper reads are ownership-checked (403) and Shipper list endpoints are customer-scoped; other roles read unscoped. `reviewer_user_id` is stamped only if still null.
- Enum-valued query filters are validated; `density_breaks` non-list → `ERR_INVALID_REQUEST`, malformed list → `ERR_INVALID_DENSITY_BREAKS`; non-numeric class field → `ERR_INVALID_REQUEST`, unrecognized number → `ERR_INVALID_CLASS_CODE`.
- Evidence counters accept ≥ 0 at shape validation; the ≥ 1 / ≥ 2 floors enforced later as `ERR_INSUFFICIENT_EVIDENCE` (422).
- PARTIAL-outcome class substitution bypasses the commodity floor; interest stays out of the ledger identity.
- Exception-agreement approval re-resolves lines only on UNBILLED/BILLED, non-`CLASS_CONFIRMED` shipments whose pickup falls in the interval and whose line uses the covered profile.

## Step 7: Run tests and iterate — 2026-09-01T15:02:00.000Z

All 8 parallel rounds pass (103/103 each). Servers cleaned up; `results.*.json` removed.

**Iterations run:** 2 sweeps of 8 parallel rounds. Sweep 1: 98/103 in all 8 rounds, the same 5 failures every round (deterministic, no flakiness). Sweep 2 after fixes: 103/103 in all 8 rounds.

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD rule; all 5 failures were fixture/assertion mistranslations or missing implementation checks.

**Fixes applied to `test_suite/`** (no `test_helpers/` change was needed — each bad precondition was built inline in a test module):

- `test_suite/test_14_endpoint_surface.py`, `test_a_capture_and_the_notice_it_produced_resolve_from_either_side`: the second shipment was tendered against `env["terminal_id"]` but captured as the *second* terminal, which PRD §2.1 correctly rejects with `ERR_NOT_RESOURCE_OWNER` ("a dock capture is only permitted when the addressed shipment's `origin_terminal_id` equals `X-User-ID`"). Now tendered against the second terminal via an env copy.
- `test_suite/test_14_endpoint_surface.py`, `DENSE_LINE`: declared class 250 contradicted the test's own "confirming capture" premise — 4 × 48×40×48 in is 213.33 cu ft, so 400 lb is 1.88 pcf, which the fixture bracket table rates at 300; declared class corrected to 300 so the capture confirms instead of reclassifying.
- `test_suite/test_15_error_surface.py`, `test_a_missing_basis_two_evidence_floors_and_a_draft_standard_each_refuse`: `evidence_bundle_count` expectation raised 1 → 4, matching PRD §3.7 verbatim ("for each accepted inspection finding on any line of the shipment, one for the finding itself plus that finding's `evidence_photo_count`") — one accepted finding with 3 photos and no cited capture is 4.
- `test_suite/test_17_version_guards_and_immediate_visibility.py`, `test_the_reweigh_gate_needs_the_percentage_and_the_pound_floor_together`: the local `_measure(weight, side_in, height_in)` helper duplicated `side_in` into both length and width, producing 48×48×40 (9.54 pcf → class 110, a spurious reclass) while the test's own asserted densities (11.45 / 11.48 pcf) require 48×40×40. Helper now takes explicit length/width/height.

**Fixes applied to `implementation/`:**

- `routes/captures.py`, `create_capture_event`: added the missing `ERR_NO_SHIPMENT_LINES` gate (PRD §3.5: "Capture requires that the shipment carries at least one line — otherwise `ERR_NO_SHIPMENT_LINES`"), placed after the CLOSED/calibration checks and before the `line_no` membership check — otherwise that PRD rule is unreachable dead code, since a zero-line shipment always trips `ERR_LINE_NO_MISMATCH` first.
- `routes/repricing.py`, `create_repricing_run`: removed the `ERR_TARIFF_NOT_PUBLISHED` gate at run creation. PRD §3.3 enumerates creation's requirements without a status precondition and assigns the check explicitly to modelling ("Modelling a run moves it `DRAFT → MODELED` and requires that the cited standard release is in `status` `PUBLISHED`"); two independent tests (a DRAFT-standard run and a SUPERSEDED-standard run) depend on creation succeeding. The modelling-time check is untouched.

**Orchestrator note:** Step 7's subagent deleted the `results.*.json` artifacts on exit, so the orchestrator re-ran the identical 8-round parallel sweep to regenerate them. Independent confirmation: rounds 1–8 each 103/103.

## Step 8: Finalize PRD — 2026-09-01T15:20:00.000Z

`PRD_FINALIZED.md` written.

### Line counts
- `PRD.md`: 441 lines; `PRD_FINALIZED.md`: 441 lines. 3 lines revised (0 inserted/deleted), **line delta 0.0%**; character delta +660 (+1.0%).

### Changes
- **§2.5 step 10** — revise — `repricing-run creation` → `repricing-run modelling`, plus an explicit statement that opening a run has no `status` precondition on the cited standard (it may be `DRAFT` or `SUPERSEDED`) — `routes/repricing.py:23-71` (no gate) / `routes/repricing.py:103-104` (gate lives at modelling, after the DRAFT status check).
- **§2.5 step 18** — revise — added `dock capture` to the endpoints guarded by `ERR_NO_SHIPMENT_LINES`, and pinned the pairwise ordering that the zero-line check precedes step 17's `ERR_LINE_NO_MISMATCH` — `routes/captures.py:82-91`.
- **§4 endpoint table, `POST /ltl/repricing-runs`** — revise — description "for a published standard" → "for a candidate standard", so the row no longer implies a creation-time publication precondition — `routes/repricing.py:23-71`.

### Per-edit pre-edit search log

**Edit 1 (§2.5 step 10)**
- (a) Subject: which endpoints the five step-10 cross-entity codes guard, and specifically where `ERR_TARIFF_NOT_PUBLISHED` is raised.
- (b) Enumerated: `grep -rn` for all five codes across `implementation/*.py`. Hits: `ERR_TARIFF_NOT_PUBLISHED` → `repricing.py:104` only (inside `model_repricing_run`, after the `status != "DRAFT"` check); `ERR_DEVICE_OUT_OF_CALIBRATION` → `captures.py:80`; `ERR_CUSTOMER_CLOSED` → `corrections.py:165`, `pricing.py:283/314/432`, `shipments.py:78/276`; `ERR_CUSTOMER_CREDIT_HOLD` → `shipments.py:80`; `ERR_EDUCATION_HOLD` → `corrections.py:265`. Also read `create_repricing_run` in full (only FK resolution, enum/interval shape, and `ERR_REPRICING_WINDOW_OVERLAP`) and `commit_repricing_run` (only `status != "MODELED"`, no tariff-status gate). Cross-checked §3.3's modelling paragraph, which already states the PUBLISHED requirement verbatim.
- (c) Adjustment: kept the replacement to the single list item and did **not** try to make the endpoint list exhaustive — the impl also raises `ERR_CUSTOMER_CLOSED` on shipment billing (`shipments.py:276`), which the original list omits; widening that would be an out-of-scope new claim, so the list stays illustrative. Wording says the guard "belongs to the modelling step" rather than "only modelling checks tariff status", so it does not deny the commit step's own (state-only) precondition.

**Edit 2 (§2.5 step 18)**
- (a) Subject: `ERR_NO_SHIPMENT_LINES` — every site that raises it, and its evaluation position relative to neighbouring capture-path checks.
- (b) Enumerated: `grep -rn "ERR_NO_SHIPMENT_LINES\|ERR_LINE_NO_MISMATCH\|ERR_OPEN_NOTICE_EXISTS"`. Sites: `captures.py:84` (new gate), `shipments.py:279` (billing, gated on `line_count < 1`); `ERR_LINE_NO_MISMATCH` only at `captures.py:89`; `ERR_OPEN_NOTICE_EXISTS` at `captures.py:134` and `corrections.py:90`. Read `create_capture_event` end-to-end to fix the actual order: ownership (l.64) → shape/dimension checks (ll.66-73) → `CLOSED` (l.75) → calibration (l.79) → zero-line (l.84) → `line_no` membership (l.86) → `ERR_OPEN_NOTICE_EXISTS` (l.132). Read `bill_shipment` (ll.267-287) to confirm billing's order (already-billed → customer closed → zero-line) still matches the unmodified base ordering. Confirmed §3.5's existing verbatim "Capture requires that the shipment carries at least one line — otherwise `ERR_NO_SHIPMENT_LINES`" needs no change.
- (c) Adjustment: dropped an earlier draft phrasing ("on dock capture this position is advanced"), which would have implied the zero-line check also moves ahead of step 16's `ERR_OPEN_NOTICE_EXISTS` — the impl in fact evaluates `ERR_OPEN_NOTICE_EXISTS` *after* both (l.132), a pre-existing 16/17 ordering deviation that is out of scope. Final wording states only the pairwise 18-before-17 relation and is silent about step 16. Also left the `CLOSED`/calibration ordering alone, since steps 9 and 10 already correctly precede step 18 in both PRD and impl.

**Edit 3 (§4 table row)**
- (a) Subject: the `POST /ltl/repricing-runs` row's implied precondition on the cited standard's status.
- (b) Enumerated: same repricing paths as Edit 1 (`create_repricing_run`, `model_repricing_run`, `commit_repricing_run`); also re-read §3.3's run-opening paragraph, which describes `new_tariff_version_id` as "the standard under evaluation" with no status requirement, and the neighbouring `/model` and `/commit` table rows (unchanged).
- (c) Adjustment: chose "candidate standard" to echo §3.3's "under evaluation" rather than adding an explicit negative precondition to the Description column.

### Items that needed no PRD change
All four `test_suite/` fixes were fixture/assertion mistranslations of rules the PRD already states verbatim: §2.1's terminal-ownership rule, the §3.1 bracket-lookup arithmetic behind `DENSE_LINE`, §3.7's `evidence_bundle_count` tally (verified against `services/notices.py:51-63`), and the §3.4 two-step cube rounding behind the `_measure` helper.

## Step 9: Complete PRD — 2026-09-01T15:38:00.000Z

All planned edits applied.

### Source vs output
- `workspace/PRD_FINALIZED.md`: 441 lines, 84,874 chars
- `workspace/PRD_COMPLETED.md`: 442 lines, 98,957 chars
- Delta: **+1 line, +14,083 chars** across **44 changed/added lines in 42 hunks** (the one added line is a bullet appended to the existing §2.2 error-format list; no new sections, no new paragraphs)

**Counts:** 33 ambiguity-pins, 11 mismatch-revisions (44 total changes)

### Per-change log (impl paths relative to `workspace/implementation/`)

- §2.1 — insert — ambiguity — shipper ownership: single reads fail `ERR_NOT_RESOURCE_OWNER`, list reads silently narrow; terminals/captures/findings carry no ownership check — auth.py:38,43; routes/_helpers.py:33
- §2.2 — revise — ambiguity — request id is `req_` + 20 uppercase-alnum chars — response.py:13
- §2.2 — revise — ambiguity — `api_request_timestamp` read from the logical clock, not wall time — response.py:19
- §2.2 — insert — ambiguity — unmatched path / bad method / unparseable body → `ERR_INVALID_REQUEST` at 404/405/400 — app.py:55-83
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` and negative `offset` → `ERR_INVALID_REQUEST`; `created_at` ties broken by insertion order — validation.py:230; db.py:139
- §2.3 — insert — ambiguity — `total_count` is the post-scope/post-filter count; `has_more` iff `offset+limit < total_count` — routes/_helpers.py:8
- §2.3 — insert — ambiguity — unrecognized enum filter value → `ERR_INVALID_REQUEST`; string compare, null never matches, filters conjunctive, unknown params ignored — validation.py:253; routes/_helpers.py:15
- §2.4 — insert — ambiguity — a row's `version` advances at most once per request however many cascade writes touch it, `updated_at` on each — db.py:112
- §2.7 — insert — ambiguity — integral rounded decimals serialize as integers (2.00 → `2`, 0.0000 → `0`) — serialize.py:222
- §3.1 — revise — ambiguity — negative `min_density_pcf`, non-object element, non-numeric fields → `ERR_INVALID_DENSITY_BREAKS`; non-array → `ERR_INVALID_REQUEST` — validation.py:191-217
- §3.1 — insert — ambiguity — `fixed_class_code` presence violations → `ERR_INVALID_REQUEST`, unrecognized code → `ERR_INVALID_CLASS_CODE` — routes/pricing.py:128
- §3.1 — revise — ambiguity — publish needs ≥1 profile (`ERR_INVALID_STATE_TRANSITION`, after the DRAFT check, before the effective-instant check); "newest published" = last by (`effective_at`, `created_at`); no published release ⇒ no bar — routes/pricing.py:33,89
- §3.2 — revise — ambiguity — `fak_class_code` presence violation → `ERR_INVALID_REQUEST`, bad code → `ERR_INVALID_CLASS_CODE` — routes/pricing.py:203
- §3.2 — insert — ambiguity — agreement approval re-resolves only lines on shipments with pickup in interval, `billing_status` UNBILLED/BILLED, `class_status` ≠ CLASS_CONFIRMED — routes/pricing.py:455
- §3.3 — revise — ambiguity — empty set ⇒ all zeros and `NEGOTIATE_FAK`; zero baseline ⇒ `modeled_delta_pct` 0.0000 with modeled revenue retained — services/modeling.py:36
- §3.3 — insert — ambiguity — exact 24-hour overlap predicate for repricing windows — routes/repricing.py:48
- §3.3 — revise — ambiguity — modelling is window-scoped, counts every scoped ACTIVE program's shipper, writes only the run; non-DRAFT → `ERR_INVALID_STATE_TRANSITION` before the PUBLISHED check — routes/repricing.py:99-121
- §3.3 — revise — mismatch — commit recomputes over the full shipment set (window not reapplied), re-evaluates scope at commit, also rewrites `modeled_shipment_count`, re-checks nothing about standard status — routes/repricing.py:129-140; services/modeling.py:82
- §3.4 — revise — mismatch — line add rejects any non-`UNBILLED` shipment (`BILLED`/`REBILLED`/`CREDITED`) with `ERR_SHIPMENT_ALREADY_BILLED` and tests `CLOSED` first — routes/shipments.py:151
- §3.4 — revise — ambiguity — a rounded cube of exactly 0 yields density 0.00 with no division — services/rating.py:117
- §3.4 — revise — mismatch — `found_class_code` holds the fully resolved class (post-override, post-floor) so it equals `effective_class_code`; weight-only capture stays in declared mode with `found_class_code` null — services/rating.py:197,206
- §3.4 — revise — mismatch — billing rejects any non-`UNBILLED` status with `ERR_SHIPMENT_ALREADY_BILLED`, before the closed-account then zero-line checks — routes/shipments.py:268
- §3.4 — revise — ambiguity — `line_charge_cents` always on the reclassed basis with the shipment-wide weight break, refreshed right after insertion — services/rating.py:309,325
- §3.5 — revise — mismatch — each measurement needs weight ≥1 and either all three dimensions or none (partial → `ERR_INVALID_REQUEST`, bad value → `ERR_INVALID_DIMENSIONS`); weight-only leaves prior dimensions/cube/density; unnamed lines untouched — routes/captures.py:34-54,70-73
- §3.5 — revise — mismatch — precondition order CLOSED → calibration → no-lines → `line_no` existence → open-notice ceiling last; `line_measurements` echoed verbatim — routes/captures.py:75-91,132,166
- §3.5 — insert — ambiguity — a non-firing capture leaves `class_status` untouched unless it stood at `DECLARED` — routes/captures.py:189-193
- §3.5 — revise — ambiguity — a firing capture drives `class_status` to `RECLASS_PENDING` from any prior value — routes/captures.py:189-190
- §3.6 — revise — ambiguity — `found_commodity_profile_id` presence rule → `ERR_INVALID_REQUEST`, unresolvable id → `ERR_COMMODITY_PROFILE_NOT_FOUND` even when forbidden; CLOSED shipment → `ERR_INVALID_STATE_TRANSITION`; recording only moves DECLARED/CAPTURED — routes/captures.py:237-262,269,288
- §3.6 — revise — ambiguity — acceptance against a CLOSED shipment → `ERR_INVALID_STATE_TRANSITION` — routes/captures.py:327
- §3.6 — revise — ambiguity — acceptance moves `class_status` only from `UNDER_INSPECTION`, never creates a notice, only refreshes `DRAFT` ones — routes/captures.py:349-357
- §3.7 — revise — ambiguity — `open_notice_count` is a recount over the four open statuses; `supersedes_notice_id` must be a same-shipment `DRAFT` else `ERR_INVALID_STATE_TRANSITION` (after version guard, before ceiling); every accepted draft bumps shipment `version`; drafting has no billing precondition — routes/corrections.py:51-149; services/notices.py:19
- §3.7 — revise — ambiguity — both deltas plus `evidence_bundle_count`/`uses_inspection_findings` refreshed again at issuance from one pass — services/notices.py:65
- §3.7 — revise — ambiguity — issuance against a `CLOSED` shipment → `ERR_INVALID_STATE_TRANSITION`; four gates in order, evidence floor before zero-delta — routes/corrections.py:151-205
- §3.7 — revise — mismatch — issuance drives `class_status` to `RECLASSED` from whatever it held — routes/corrections.py:151-205
- §3.8 — insert — ambiguity — `education_required_at` keeps its stamp after completion — routes/core.py:143
- §3.9 — insert — ambiguity — `evidence_doc_count` required non-negative integer; negative → `ERR_INVALID_REQUEST`, 0 falls to the evidence floor — routes/corrections.py:240
- §3.9 — revise — mismatch — supplement request also requires the notice be `DISPUTED`; `reviewer_user_id` stamped only when null (first reviewer sticks) — routes/corrections.py:332-346
- §3.9 — revise — ambiguity — `additional_doc_count` required non-negative integer; notice must be `EVIDENCE_REQUESTED` — routes/corrections.py:365-371
- §3.9 — revise — mismatch — resolve requires notice `DISPUTED`/`EVIDENCE_REQUESTED` (before SoD); `ERR_INVALID_PARTIAL_OUTCOME` checks run after state/SoD; non-numeric class → `ERR_INVALID_REQUEST`; `reviewer_user_id` retained if already set — routes/corrections.py:391-425,468-473
- §3.9 — revise — mismatch — PARTIAL substitutes on every line whose found class differs in either direction, writing both class fields verbatim with no floor and no provenance change; all line charges and the delta count recomputed; `billing_status` forced to `CREDITED` — routes/corrections.py:432-447,496
- §3.9 — revise — mismatch — OVERTURNED reverts every line with `effective_class_code` re-derived (floor still binds, `class_floor_applied` restated); `billing_status` forced to `CREDITED`; `class_status` steps back only from `RECLASSED` — routes/corrections.py:449-461; services/rating.py:217
- §3.9 — insert — ambiguity — no credit bucket is clamped at zero; negative freight and interest buckets are recorded as computed — routes/corrections.py:477-489
- §3.10 — revise — ambiguity — sweep skips notices with any dispute including `RESOLVED`; recomputes each shipment's `open_notice_count` and each shipper's record (incl. strike count) once; `200 OK` with creation-ordered `upheld_notice_ids`, 0/empty when nothing qualifies — routes/corrections.py:206-233
- §3.10 — insert — ambiguity — close check order: CLOSED → `ERR_INVALID_STATE_TRANSITION`, UNBILLED → `ERR_SHIPMENT_NOT_BILLED`, class_status outside {DECLARED,CAPTURED,RECLASSED} → `ERR_INVALID_STATE_TRANSITION`, open notices last — routes/shipments.py:291-305

No behavior was invented beyond what the implementation exhibits; §4 endpoint table and §5 error catalogue needed no edits.

## Pipeline complete — 2026-09-01T15:40:00.000Z

Final artifact inventory verified on disk: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 modules), `test_suite/` (conftest + 17 test modules, 103 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}`, `workspace/implementation/` (23 files + `results.{1..8}.json`, all 8 rounds 103/103).
