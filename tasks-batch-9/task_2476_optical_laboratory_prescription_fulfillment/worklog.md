# Worklog — task_2476_optical_laboratory_prescription_fulfillment

## Step 1: Create task directory — 2026-09-02T22:08:27.659Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2476_optical_laboratory_prescription_fulfillment` and its `workspace/` subdirectory. Index 2476 was pre-assigned by the orchestrating pipeline (no ./tasks/ scan performed, per instruction, to avoid collision with the up-to-32 concurrent pipelines on this host).

## Step 2: Generate scaffold artifacts — 2026-09-03T01:35:00Z

Generated `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8) and `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9) from the scenario description alone, per the `prd-bench-scaffold-generator` skill. No sibling task under `tasks/` was inspected.

Shape: 16 entities, 7 state machines, 2 OCC concurrency rules, 14 calculation rules, 71 ordered validations, 63 endpoints, 72 errors, 6 roles. §1.8 carries 9 rules x 2 instances = 18 executable instances; §1.9 carries 78 instances across the nine sections (65 executable + 13 `excluded_because` stubs citing §1.8).

`scaffold_lint.py` verdict: clean lint (1016 calls scanned across §1.8+§1.9).

## Step 2 (orchestrator record): Generate scaffold — verbatim subagent summary — 2026-09-03T01:40:00.000Z

Done. All three artifacts are generated and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2476_optical_laboratory_prescription_fulfillment/`):
- `SCAFFOLD.yaml` — 3394 lines, §1.0–§1.7
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2193 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4711 lines, single key `scaffold_corner_design`

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2476_optical_laboratory_prescription_fulfillment/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2476_optical_laboratory_prescription_fulfillment/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2476_optical_laboratory_prescription_fulfillment/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     16
  §1.8 instances scanned:     18
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1016

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Shape of the scaffold**
- Complexity profile: difficulty `beyond_expert`, primary `workflow_orchestration`, secondary `pricing_engine`, layers `dual_variant_calculation` / `cascading_side_effects` / `rate_threshold_triggers` / `optimistic_concurrency`, role model `segregation_of_duties`, consistency `immediate`.
- 16 entities: Prescriber, PrescriptionRecord, Patient, InsurancePlan, LensDesign, LensBlankLot, RxOrder, FrameLayout, LabJob, LabMachine, FinishingBay, LabOperation, QualityInspection, ToleranceStandard, RemakeCase, SettlementEntry (event row).
- 7 state machines (RxOrder carries two independent dimensions — `fulfillment_status` and `billing_status`), 2 OCC rules (`expected_rx_order_version` on layout create, `expected_lab_job_version` on operation booking), 14 calculations (3 of them dual-variant: quote, turnaround, responsibility split), 71 ordered validations, 63 endpoints, 72 errors, 6 roles.

**Design-file instance counts**
- §1.8: 9 rules x 2 = **18** executable instances (dual-variant quote/responsibility, non-linear two-dimension order machine, four-hop remake and three-hop breakage cascades, priority-pair conflicts, tolerance/diameter boundary pairs, cross-entity state dependencies, machine-buffer and bay-capacity temporal overlap, benefit-void and cancel compensations).
- §1.9: **78** instances across all nine sections — 65 executable + 13 `excluded_because` stubs (entities 12, state_machines 12+4, calculations 8+6, validations 8+1, endpoints 5, errors 12, rbac 4, cross_cutting 3+2, consistency_model 1). Every stub cites an existing §1.8 `rule_id / instance_name`; no name is reused across the two files.

**Verification beyond the lint:** replayed every new §1.9 trigger against the §1.4 priority ladder to confirm the intended error wins (e.g. `ERR_ACTIVE_LAB_JOB_EXISTS` at 285 beating `ERR_ORDER_STATE_INVALID` at 290; `ERR_OPEN_REMAKE_CASE_EXISTS` at 615 reachable only via the scrapped-job-plus-replacement path; `ERR_UNAUTHORIZED` at 40 preempting the FK check at 30), and re-derived the money/geometry literals (self-pay gross 26985, cumulative writeoff tiers 6746 → 16191, TOLERANCE_DELTA share 25 % / chargeback 4498 on basis 17990, layout 58.0 mm). No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-03T01:32:51.191Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T01:50:00.000Z

Orchestrator anti-truncation check: `PRD.md` is 479 lines; sections §1–§5 all present; the file ends on a complete final table row (`| ERR_REMAKE_NOT_DELIVERABLE | 409 |`) of §5 "Error Code Catalogue" — a real section boundary, not mid-sentence. No regeneration needed.

Verbatim subagent summary:

PRD complete and verified.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2476_optical_laboratory_prescription_fulfillment/workspace/PRD.md` — **479 lines**, last section **"5. Error Code Catalogue"**, ending on the final error-table row (`ERR_REMAKE_NOT_DELIVERABLE` | 409). No truncation; document ends at a real section boundary with no audit footer.

## Section list
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 11 subsections: 2.1 RBAC, 2.2 API Response Structure (fixed block), 2.3 Pagination, 2.4 Record Identity/Timestamps/Logical Clock, 2.5 Optimistic Concurrency Control, 2.6 Money/Geometry/Measurement Precision, 2.7 The Two Dimensions of an Order, 2.8 Cascade Discipline/Compensation/Conservation, 2.9 Segregation of Duties, 2.10 Order of Rejection, 2.11 Nested/Referenced Resource Resolution
- §3 Business Logic & Workflows — 9 subsections: 3.1 Registry & Catalogue, 3.2 Prescription Intake/Expiry/Verification Ladder, 3.3 Order Opening & Provisional Quote, 3.4 Frame Tracing/Decentration/Minimum Blank, 3.5 Committing to the Lab, 3.6 Shop-Floor Occupations, 3.7 Per-Eye Inspection/Rework Loop/Release, 3.8 Remake Cases/Warranty Write-Offs/Responsibility, 3.9 Benefit Application/Settlement/Dispensing/Withdrawal
- §4 Endpoint Definitions — 1 intro paragraph + 4-column table, all **63** endpoints
- §5 Error Code Catalogue — 2-column table, all **72** errors

## Hard Contract reports
- **Contract 1 — Field-Name Coverage: PASS.** 156/156 scaffold field / `request_body` / `query_param` / `path_param` names appear verbatim in backticks. 0 missing (machine-verified).
- **Contract 2 — Rule Coverage: PASS.** All 52 state-machine transitions appear as verbatim state pairs (e.g. `RELEASED → SCRAPPED`, `PROVISIONAL_QUOTED → CANCELLED_NO_CHARGE`, `AVAILABLE → DEPLETED`); all 72 error IDs are triggered in §2/§3 narrative, not only in the §5 table; all 14 `calculations` rules are expressed as prose with every numeric constant present; all 71 validations are covered with explicit priority ordering (the five-step global ladder in §2.10 plus per-workflow gate orders); both §1.2.1 concurrency rules are in §2.5; cross-entity cascades (prescriber-standing 3-hop, breakage 3-hop, remake 4-hop, withdrawal unwind, replenish promotion) are stated hop-by-hop with their non-restoration semantics.
- **Contract 3 — §3 Path Purity: PASS.** 388 distinct backtick tokens across §3's 173 lines; 0 start with `/`, 0 are bare HTTP methods, 0 combine method+path. Endpoints are named only by state-transition framing, role + action verb, or capability description.

## Other verifications
- §2.2 diffs byte-for-byte clean against `section-2.2-response-structure.md`.
- No pseudocode operators, no math-notation function calls (`min(`, `max(`, `abs(`, `round(`), no fuzzy words.
- The two withheld design files were never opened, grepped, or referenced.

## Scaffold inconsistencies resolved (recorded so they are not re-litigated)
- Auth headers use `X-User-ID`/`X-User-Role` per SKILL.md, not the scaffold's `X-Role` (matches sibling PRDs 2470–2475).
- `axis_delta` follows the §1.3 calculation rule (lesser of the raw gap and 180 minus the raw gap), not the entity description's 360-based variant.
- The money identity is stated as declared, with `invariant_holds` framed as reporting whether it currently holds (it is arithmetically exact only for the `FINAL` variant).
- Where entity domains are wider than enforced validation ranges (cylinder, `a_mm`, `ed_mm`, `dbl_mm`), both are given with the gate marked as what intake/tracing enforces.
- No error ID was invented for duplicate `machine_code`/`bay_code`; uniqueness is stated as a field constraint only.

## Step 6: Generate implementation — 2026-09-03T02:45:00.000Z

Verbatim subagent summary:

Implementation is complete and verified.

## Files written
All under `workspace/implementation/` (3,310 lines total):

Infrastructure
- `start.sh` — guarded `pip install`, `export PORT="${PORT:-10000}"`, `exec python3 app.py`
- `requirements.txt` — `flask>=2.0`
- `app.py` — app factory, 6 blueprints, `ApiError`/`HTTPException`/catch-all handlers, binds `0.0.0.0:$PORT`
- `store.py` — 16 in-memory dicts + logical clock (epoch `2026-08-01T00:00:00Z`), `stamp_common`/`stamp_event`/`touch`/`sorted_rows`
- `envelope.py` — meta/response_type/data envelope, `req_` + 20 alnum ids, clock-stamped timestamps, pagination (default 10, clamped 1–100)
- `errors.py` — all 72 error IDs with statuses; `validate.py` — structural layer (priority 10); `auth.py` — `X-User-Role` (with `X-Role` alias) + `X-User-ID`
- `calc.py` — 14 calculation rules (geometry, routing, blank selection, machine/bay feasibility, TAT/expedite, quote, benefit waterfall, inspection deltas/verdict, responsibility split, writeoff tiers, warranty window)
- `services.py` — cascades (prescriber-standing 3-hop, cancel effects, backorder promotion), blank ledger, settlement appends, derived aggregates
- `serializers.py` — per-entity projections; derived fields (`verified_rx_count`, `benefit_used_cents`, `patient_balance_due_cents`) computed at read time; `_seq`/`_holds_allocation`/`_backorder_count` never exposed

Routes: `routes/clock.py`, `registry.py`, `prescriptions.py`, `orders.py`, `lab.py`, `remakes.py`

## Verification
- **Endpoints: 63/63.** A script diffed the SCAFFOLD endpoint table against Flask's `url_map`: `missing: []`, `extra: []`.
- **Roles: 0 mismatches.** Each view's `require_roles(...)` set was compared to the declared `roles:` list for all 63 endpoints.
- **`bash start.sh` boots and serves on `$PORT`** from a fresh process (verified on several ports; `GET /rx-orders?limit=1` -> 200 with an empty `data` array and a well-formed envelope, `POST /_clock/set_current_utc` -> 200).
- Two end-to-end smoke suites pass with no tracebacks: full happy path (registry -> rx verify -> order -> layout -> job -> surfacing/edging ops -> FAIL inspection -> rework cycle -> PASS pair -> release -> benefit application -> settle -> remake case -> adjudicate) and the dark paths (stock-route surfacing refusal, stale-version 412s, bay capacity, machine buffer conflict, window validity, breakage -> `BLANK_BACKORDER` -> replenish promotion, cancel with blank return, prescriber-suspension cascade, self-pay `SELF_PAY_FINAL`, settlement bounds, dispense gate).
- Storage is in-memory only: a grep for `sqlite|open(|json.dump|pickle|shelve|/tmp` across the implementation returns nothing. Every dict starts empty; no entity data is seeded, preloaded or hardcoded. `test_suite/`, `test_helpers/`, and the two design YAMLs were never read.

Interpretation decisions worth flagging: `expedite_fee_cents` legitimately differs between the PROVISIONAL and FINAL quotes (the surfacing TAT penalty moves the order into a lower expedite-rate band); RemakeCase `defect_codes` members outside the declared vocabulary are rejected structurally as `ERR_VALIDATION` (the scaffold reserves `ERR_UNKNOWN_DEFECT_CODE` for inspection `cosmetic_defect_codes` only); machine/bay availability is enforced both at operation creation (declared rules 370–400) and again at start (state-machine precondition). All test servers I started have been stopped and `__pycache__` removed.

## Step 5: Generate unit tests — 2026-09-03T03:55:00.000Z

Verbatim subagent summary:

Suite complete and verified.

## Files written

**`test_helpers/` (9 files)** — `__init__.py`, `api_client.py` (63 endpoint methods), `api_errors.py` (72-member `ApiErrorId` + `HTTP_STATUS_CODES`), `assertions.py` (28 helpers), `constants.py`, `factories.py` (~30 payload builders), `fixtures.py` (scenario ladders + 11 `read_*` shortcuts), `test_users.py`, `types.py`.

**`test_suite/` (27 files, 141 tests)** — `test_01`–`test_18` are queue A (one file per §1.8 rule instance); `test_19`–`test_27` are queue B (one file per §1.9 section).

## Test counts per queue

| Queue | Files | Tests | Instances covered |
|---|---|---|---|
| A — Difficulty (§1.8) | 18 | 56 | 18 / 18 (every instance >=2 tests) |
| B — Corner (§1.9) | 9 | 85 | 65 / 65 non-stub |

Queue B by section: entities 12/12 -> 12 tests; state_machines 12 non-stub -> 15; calculations 8 non-stub -> 8; validations 8 non-stub -> 10; endpoints 5/5 -> 8; errors 12/12 -> 15; rbac 4/4 -> 7; cross_cutting_complexity_layers 3 non-stub -> 7; consistency_model 1/1 -> 3.

## Instances skipped

**No instance was skipped for PRD-derivability.** The 13 §1.9 instances carrying their own `STUB excluded_because` marker were correctly left untranslated (they cross-reference a §1.8 instance that already pins the same literals): 6 in `calculations`, 4 in `state_machines`, 2 in `cross_cutting_complexity_layers`, 1 in `validations`.

**Two individual design assertions omitted** as not uniquely derivable from the PRD, with the rest of each instance translated:
- `endpoints/patient_creation_read_and_listing_round_trip` asserts a self-pay patient's `benefit_period_start == null`, but §3.1 says it "defaults to `2026-01-01`" unconditionally with no self-pay exception.
- `rbac/lab_and_benefits_roles_cannot_perform_optician_only_writes` asserts its third trigger (POST /remake-cases naming an order id as `lab_job_id`) yields `ERR_UNAUTHORIZED` 403 rather than `ERR_LAB_JOB_NOT_FOUND`, but §2.10 orders "3. Referenced entity exists" *ahead of* "4. Role permitted" and §2.1 confirms authorisation runs "after the addressed and referenced entities have been resolved" — so the PRD uniquely derives 404. The instance's other two unauthorized writes are covered.

## Verification passes (all clean)

- Citation checker (AST-extracts every `PRD n.m: "…"`, requires a verbatim single-line substring hit *and* cross-checks the claimed section against the nearest preceding header): **147 citations, 0 problems**. This pass caught and fixed three real defects in already-written queue A files — a missing `§` in `test_01`, a fabricated "Verification runs four gates in order" sentence in `test_09`, and a truncated expiry sentence in `test_09`.
- Tag audit: exactly one `Design:` line per test, always the last docstring line; every tag resolves to a real non-stub instance name; no dual tags; no non-stub instance left untested.
- No scaffold references anywhere in test comments or docstrings.
- `python -m py_compile` on all 27 test files and all 9 helpers: OK.
- `pytest --collect-only`: **141 tests collected**, no collection errors.

The isolation constraint held throughout — nothing under `workspace/implementation/` was read or written.

## Step 7: Run tests and iterate — 2026-09-03T03:26:56.000Z

Orchestrator verification (per the known failure mode where a Step 7 agent claims a clean sweep without leaving artifacts): read all 8 `workspace/implementation/results.$i.json` back from disk myself — each reports `passed=141, total=141, failed=0, errors=0, skipped=0` with a 141-entry `tests` array, all written 2026-09-03T03:19:23Z. `grep -c Terminated workspace/sweep.log` = 0, so the rounds were properly detached under `setsid` and no reaping artifacts contaminated the run.

Verbatim subagent summary:

Verified clean on disk: both sweeps green, 141/141 in every round.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (each round `--isolation per-test-server`, 141 tests, ~260s wall).

- Sweep 1 (baseline, as delivered): all 8 rounds `141/141 passed, 0 failed, 0 errors, 0 skipped`. No flakiness surfaced — no test failed in any round, so the STEP 0 union set was empty and the diagnostic protocol had nothing to triage.
- Sweep 2 (after the single implementation edit below): all 8 rounds again `141/141`, `tests` array length 141 in each `results.$i.json`, zero `Terminated` lines in the sweep log (rounds were correctly detached under `setsid`, so no reaping artifacts).

**Tests deleted:** none. No test failed, so no test was ever a candidate for STEP 1 silence/collapse review.

**Fixes applied to `test_helpers/`:** none needed. Spot-audited `test_suite/conftest.py` and `test_helpers/assertions.py` to confirm the suite is not passing vacuously — assertions are real (exact `error_id` checks, event-row shape checks that assert absence of `updated_at`/`version`, three conservation checks), and no fixture swallows failures.

**Fixes applied to `implementation/`:**
- `workspace/implementation/auth.py`, function `acting_role()` — removed a non-PRD `X-Role` header alias (the code fell back to reading `X-Role` when `X-User-Role` was absent/empty, citing SCAFFOLD §1.7 in a comment). PRD §2.1 states the acting role travels in `X-User-Role` only, and that an absent header is `ERR_UNAUTHORIZED`; the alias was an implementation capability with no PRD sentence behind it and it weakened that gate. No test referenced `X-Role`, and the follow-up sweep confirmed the removal is behaviour-neutral for the suite.

**Other integrity checks:** storage is in-memory only (`store.py` `Store.reset()` initialises every collection empty per boot); no seeding, preloading or hardcoded entities anywhere in `implementation/`.

## Step 8: Finalize PRD — 2026-09-03T03:30:00.000Z

Step 8 was run (not skipped): Step 7 applied one `implementation/` fix, so the skip condition (zero deletions AND zero test fixes AND zero impl fixes) did not hold. Orchestrator check: `diff -q PRD.md PRD_FINALIZED.md` reports the files identical, matching the subagent's stated outcome.

Verbatim subagent summary:

**Result: `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`. Zero edits — no manufactured changes.**

- Line counts: PRD.md 479 / PRD_FINALIZED.md 479, %-delta 0.0%. Identical md5 (`47f48da8...`), `diff -q` clean.
- Change bullets: none.

Why nothing needed pinning
- `<step_7_diff>` contains exactly one item that touches `implementation/`: removal of the `X-Role` header alias from `acting_role()` in `workspace/implementation/auth.py:19-21`. Zero test deletions, zero `test_suite/`/`test_helpers/` fixes, so there are no other traceable items in scope.
- That item was a **PRD-mismatch resolved in the implementation's favour of the PRD**, not a PRD silence. PRD.md:15 (§2.1) already states uniquely: two headers `X-User-ID` and `X-User-Role`, "If either header is absent, if `X-User-Role` names something that is not a recognised role, or if the named role is not authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)." Post-fix `acting_role()` reads `X-User-Role` and nothing else — exactly what that sentence says. Adding a sentence like "the role is read from `X-User-Role` only" would be pure redundancy, not a pin.

Per-edit pre-edit search log (run for the one candidate edit, which was then dropped)
- (a) Subject: source of the acting role/user headers and the `ERR_UNAUTHORIZED` header gate.
- (b) Impl paths enumerated: grepped `headers|acting_role|acting_user_id|require_roles|X-Role|X-User-Role` across all of `implementation/` (plus `test_suite/`, `test_helpers/`). The only header reads in the entire codebase are `auth.py:21` (`X-User-Role`) and `auth.py:25` (`X-User-ID`); `auth.py:28-40` `require_roles()` is the single gate (both-present -> known role -> permitted, all raising `ERR_UNAUTHORIZED`). All ~80 callsites — `routes/orders.py`, `routes/lab.py`, `routes/remakes.py`, `routes/prescriptions.py`, `routes/registry.py`, `routes/clock.py` — funnel through it; bare `require_roles()` implements the "Any" column of PRD.md:336, and the identity comparisons (`routes/prescriptions.py:177` prescriber-of-record, `routes/lab.py:238/379`, `routes/remakes.py:147`, `routes/orders.py:43`) all consume `acting_user_id()`/the `require_roles()` return, never a header directly. No residual `X-Role` reference anywhere.
- (c) Wording adjustment: none — edit dropped entirely, because every enumerated path is already correctly and uniquely described by the existing PRD §2.1 prose. Writing anything new here risked narrowing a sentence that already holds globally (a NO-NEW-MISMATCH hazard with no upside).

One adjacent observation, deliberately **not** patched: `require_roles()` uses falsy checks (`if not user_id or not role`), so a present-but-empty header behaves as absent. For `X-User-Role` the PRD already covers it ("names something that is not a recognised role"); for an empty `X-User-ID` the PRD is arguably silent, but that behaviour predates Step 7, was not touched by any `<step_7_diff>` item, and is therefore out of the hard scope.

## Step 9: Complete PRD — 2026-09-03T03:37:49.839Z

Orchestrator check: `workspace/PRD_COMPLETED.md` exists, 479 lines / 105,287 chars, still 5 top-level sections (no sections added), and it ends on the same complete final table row of §5 as the source PRD — no truncation.

Verbatim subagent summary:

The walk is complete. All ten implementation modules plus the six route files were read end to end.

## Summary

**Files:** `PRD_FINALIZED.md` 479 lines / 98,872 chars -> `PRD_COMPLETED.md` 479 lines / 105,287 chars (**char-delta +6,415**; zero new lines, zero new sections, zero new paragraphs — every change is an in-paragraph or in-table-cell insert/revision).

**Counts:** 36 changes across 34 lines — **24 ambiguity-pins**, **12 mismatch-revisions**.

### Changes

- §2.1 RBAC — revise — ambiguity — an *empty* `X-User-ID`/`X-User-Role` is treated as absent, not as a value — `auth.py:32`
- §2.2 Success envelope — revise — ambiguity — `api_request_timestamp` is read from the logical clock, so it repeats verbatim within one logical instant — `envelope.py:26`
- §2.3 Pagination — revise — ambiguity — out-of-range `limit`/`offset` are silently clamped and unparseable values fall back to defaults; a paginated read never returns `ERR_VALIDATION` — `envelope.py:57-76`
- §2.3 Pagination — revise — ambiguity — `created_at` ordering is realised as insertion order, which is also the tie-break for every "newest/oldest row" rule — `store.py:88`
- §2.4 Logical clock — revise — ambiguity — the clock endpoint returns `current_utc` as the single field of its `data` — `routes/clock.py:23`
- §2.8 Money identity — revise — **mismatch** — the identity holds only from the final quote onward; `invariant_holds` is false on any provisionally quoted order with a nonzero projection — `routes/orders.py:138`
- §3.1 Lens designs — revise — **mismatch** — `min_blank_diameter_mm` is validated and returned but never consulted by any workflow; also `stock_sku_available` optional/defaults false and `base_curve` optional/null — `routes/registry.py:194-197`
- §3.1 Tolerance standards — revise — ambiguity — `axis_tolerance_degrees` is a whole number; `allowed_cosmetic_defect_codes` is a mandatory array whose members are unrestricted free strings — `routes/registry.py:230-232`
- §3.1 Blank lots — revise — ambiguity — an *absent* `added_qty` is caught structurally ahead of the lot lookup, while a present-but-invalid one is caught last — `routes/registry.py:309-315`
- §3.1 Shop resources — revise — **mismatch** — `machine_code` and `bay_code` carry no uniqueness gate at all — `routes/registry.py:327-379`
- §3.2 Resubmission — revise — ambiguity — corrections bypass the intake gates: a future issue date and an out-of-range PD are both accepted — `routes/prescriptions.py:221-227`
- §3.2 Standing cascade — revise — ambiguity — hop 3 additionally requires `billing_status` still `PROVISIONAL_QUOTED` — `services.py:270`
- §3.3 Order payload — revise — ambiguity — `requested_coatings` is mandatory (may be empty); unknown coating codes are not structural — `routes/orders.py:32`
- §3.4 Decentration — revise — **mismatch** — all three decentration figures are themselves rounded half up to one decimal before feeding the blank requirement — `calc.py:153-155`
- §3.6 Starting an occupation — revise — **mismatch** — a third gate exists after the job gate: `ERR_MACHINE_NOT_AVAILABLE` / `ERR_BAY_NOT_OPEN` — `routes/lab.py:244-251`
- §3.6 Reporting breakage — revise — **mismatch** — the `RUNNING` state gate is evaluated *before* the edging-applicability gate — `routes/lab.py:282-285`
- §3.6 Dropping a booking — revise — ambiguity — `cancel_reason` is mandatory and non-empty — `routes/lab.py:328`
- §3.7 Inspection payload — revise — ambiguity — `measured_axis` alone is optional (0–180, integer), stored null and treated as 0 in the circular distance — `routes/lab.py:373`, `calc.py:348`
- §3.7 Fork-join — revise — ambiguity — a first-of-cycle `PASS` writes nothing to the job row, so its `version`/`updated_at` do not advance — `routes/lab.py:441-449`
- §3.8 Defect vocabulary — revise — ambiguity — remake `defect_codes` are enforced structurally (`ERR_VALIDATION`), unlike cosmetic codes — `routes/remakes.py:38-39`
- §3.8 Warranty write-off — revise — ambiguity — the `LAB_WRITEOFF` entry carries the negative *delta* against the previous write-off and is omitted when that delta is zero — `routes/remakes.py:107-110`
- §3.9 Benefit application — revise — ambiguity — the route comes from the **newest** non-`SCRAPPED` job, `RELEASED` included — `services.py:64-69`
- §3.9 Benefit void — revise — ambiguity — the `BENEFIT_REVERSAL` entry is appended unconditionally, even at amount 0 — `routes/orders.py:207-208`
- §3.9 Dispensing — revise — **mismatch** — only two gates exist; `billing_status` is never inspected, so a zero-portion order dispenses from `BENEFIT_APPLIED`/`SELF_PAY_FINAL` — `routes/orders.py:244-247`
- §3.9 Withdrawal — revise — **mismatch** — the unwind targets the newest job that is not already `RELEASED`/`SCRAPPED` (the in-progress gate uses the newest job outright); nothing is unwound when none qualifies — `routes/orders.py:261`, `services.py:225`
- §3.9 Withdrawal — revise — ambiguity — `insurance_benefit_cents` is zeroed alongside the other four money fields — `services.py:244`
- §4 `POST /prescriptions/{id}/verify` — revise — **mismatch** — a record disagreement is refused with `ERR_PRESCRIBER_RECORD_MISMATCH`, never routed to attestation — `routes/prescriptions.py:158-160`
- §4 `POST /prescriptions/{id}/prescriber-attest` — revise — **mismatch** — takes only a mandatory `attestation_statement`; no correction fields — `routes/prescriptions.py:172`
- §4 `POST /prescriptions/{id}/resubmit` — revise — **mismatch** — `REJECTED` is the only admissible starting state — `routes/prescriptions.py:216`
- §4 `GET /patients` — revise — ambiguity — also filterable by patient status — `routes/registry.py:175`
- §4 `GET /rx-orders` — revise — ambiguity — also filterable by prescription and lens design — `routes/orders.py:125`
- §4 `GET /rx-orders/{id}/frame-layouts` — revise — ambiguity — also filterable by layout status — `routes/orders.py:275`
- §4 `GET /lab-jobs` — revise — ambiguity — also filterable by layout and blank lot — `routes/lab.py:88`
- §4 `GET /lab-operations` — revise — ambiguity — also filterable by blank lot — `routes/lab.py:220`
- §4 `GET /quality-inspections` — revise — ambiguity — also filterable by resolved tolerance standard — `routes/lab.py:474`
- §4 `GET /remake-cases` — revise — **mismatch** — filtered by lab job and linked inspection; there is no order filter, since a case carries no order id — `routes/remakes.py:132`

### Notable non-changes (impl already uniquely pinned by PRD)
Blank-lot ranking and tie-breaks, machine buffered-overlap and bay closed-interval counting, expedite band/ceiling arithmetic, the coating pool waterfall with per-component coinsurance rounding, calendar-month expiry clamping, tolerance-standard resolution ordering, the cumulative remake write-off from the write-off-free base, `tolerance_delta_share`, the four-hop remake chain, and the segregation-of-duties placements all match the PRD as written.

---

## Pipeline complete — 2026-09-03T03:37:49.839Z

All nine steps ran to completion. Final state: 3 scaffold artifacts, 479-line PRD (+ PRD_FINALIZED.md + PRD_COMPLETED.md), 10 test_helpers files, 27 test files / 141 tests, 63-endpoint Flask implementation, and 8 passing sweep result files (141/141 each).
