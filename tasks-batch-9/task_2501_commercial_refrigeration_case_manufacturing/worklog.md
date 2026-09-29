# Worklog — task_2501_commercial_refrigeration_case_manufacturing

## Step 1: Create task directory — 2026-09-03T02:01:30.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2501_commercial_refrigeration_case_manufacturing` and its `workspace/` subdirectory. Index 2501 was pre-assigned by the invoker; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Scaffold generation complete — 2026-09-03

Wrote all three artifacts from the scenario description plus the scaffold-generator specification only; no sibling `task_*/` directory was listed, globbed, grepped or read at any point.

- `SCAFFOLD.yaml` (§1.0–§1.7): 14 entities, 8 state machines, 2 concurrency rules, 12 calculations, 39 ordered validations, 52 endpoints, 52 errors, 9 roles.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8): 9 rule_ids × 2 instances = 18.
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9): 9 sections, 89 instances (75 with `test_recipe`, 14 stubs citing §1.8 instances by name).

Verification performed: `scaffold_lint.py` → `VERDICT: clean lint`; a forced re-lint with the negative-trigger name exemption disabled also produced 0 violations; placeholder-closure, name-uniqueness, stub-citation, grounds-resolvability and entity-scoped assert-field audits all clean; every numeric literal (airflow loads 442.91/347.09, charge 7320, energy indices 0.568/0.644/0.823/17.568, all pricing waterfalls, warranty accruals) recomputed from the §1.3 formulas and matched.

Fixes applied during verification: added the missing `Shipment.received_by_name` field (the handoff endpoint accepted it as input but no field held it); corrected a `refrigerant_charge_basis` cross-reference from validation priority 9 to 11; replaced three asserts referring to non-existent fields (`current_utc`, `certified_label_id`, `StorePlanLine.linear_feet`); corrected one stub rationale's cited literals; removed "simultaneous"-family wording from three calculation notes.

## Step 3: Copy shared files — 2026-09-03T03:42:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md`. Also verified Step 2 outputs: SCAFFOLD.yaml (2841 lines, contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` key), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1766 lines, single top-level key `scaffold_difficulty_design`), SCAFFOLD_CORNER_DESIGN.yaml (2443 lines, single top-level key `scaffold_corner_design`).

## Step 4: Generate PRD — 2026-09-03T03:55:00.000Z

Subagent summary (verbatim):

PRD generated and verified complete.

**Output:** `workspace/PRD.md` — **451 lines**, 91,861 chars. Tail read back: file ends at a completed §5 Error Code Catalogue table (final row `` `ERR_CREDIT_LIMIT_EXCEEDED` | 402 ``), no truncation, no audit footer. I did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`, and nothing about task difficulty was written into the PRD.

## Structure (24 headings)

- **§1 Introduction** — 3 paragraphs (pain-point angle: four disconnected systems; the two governing ideas, *pinning* and *cascading holds*; the logical clock as compliance record).
- **§2 Global Specifications** — 10 domain-derived subsections: 2.1 RBAC · 2.2 API Response Structure (verbatim, byte-identical — verified) · 2.3 Pagination · 2.4 Resource Identity, Revision Counters and the Logical Clock · 2.5 Request Evaluation Order · 2.6 Rounding Discipline · 2.7 Design-Revision Pinning and Stale-Parent Rejection · 2.8 Compliance Holds and the Cascade Discipline · 2.9 Segregation of Duties · 2.10 Interval Conventions.
- **§3 Business Logic** — 9 subsections grouped by lifecycle-then-value-chain: catalogue seeding · case design + airflow model · chamber scheduling and testing · certification/labelling/revocation · refrigerant transition and the 5-hop cascade · store plans (config/pricing/approval) · plant release and fabrication routing · shipment and installation handoff · warranty, field service and reserve ledger. No tables, no code fences, no field lists.
- **§4** 52-row endpoint table, exactly 4 columns. **§5** 52-row error table, exactly 2 columns.

## Coverage per scaffold dimension

14 entities · 8 state machines (all **52** transitions rendered in explicit `FROM → TO` arrow form) · 12 calculations · 39 validations · 52 endpoints · 52 errors · 9 roles · 2 concurrency rules — all present.

```
Field coverage check:
- entities[].fields: 150 required, 150 present, 0 missing
- endpoints[].request_body: 95 required, 95 present, 0 missing
- endpoints[].query_params: 17 required, 17 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 39 checked, 39 expressed in prose (ranks 1-8 as the explicit
  universal ladder in §2.5; ranks 9-39 each quoted with its global rank number at the
  workflow it guards), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (POST /energy-tests +
  expected_case_model_version + ERR_STALE_CASE_MODEL_VERSION/412; POST /shipments +
  expected_store_plan_version + ERR_STALE_STORE_PLAN_VERSION/412), 0 missing
- state_machines[].transitions: 52 checked, 52 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed (all constants embedded in business prose,
  rounding order pinned, no operator syntax), 0 missing
- validations[] conditions: 39 checked, 39 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 52 checked, 52 expressed (incl. cross-entity version
  bumps on energy-test create, label issue and shipment create), 0 missing
- entities[].fields[] structured content: 150 checked, 150 reconstructible from prose
  (defaults, initial values, enum members, and the two common_fields:false catalogue entities
  that carry only id and created_at), 0 missing
- sibling-branch symmetry: 8 groups checked (FOAM_INJECTION door_type branch; 3 shipment
  cancel source states; 2 claim-deny source states; 6 engineering-change source states;
  nameplate vs installed charge basis; lab vs field index variant; open-estimate vs resolved-
  actual reserve; FAIL/SCRAP rework-limit complements), 8 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 854
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also spot-checked: zero pseudocode operators (`==`, `>=`, `+=`, …) anywhere in prose; zero fuzzy/approximating words (the only `about`/`around` hits are "learns nothing about", "cares about", "turnaround"); all 9 role names, all state enum values and all 52 error IDs appear verbatim.

**Orchestrator verification of the known truncation failure mode:** independently read the tail of `workspace/PRD.md` — it ends at row `| ERR_CREDIT_LIMIT_EXCEEDED | 402 |`, a complete final table row of a complete §5, not mid-sentence. Counted 54 pipe-rows in each of §4 and §5 (52 data rows + header + separator each). Grepped for `expert`/`difficult` — 0 hits, so the difficulty instruction did not leak into the PRD. No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T04:40:00.000Z

Orchestrator note on launch: Steps 5 and 6 were intended to go out in a single assistant message. Step 6 in fact went out in the immediately following message (a few seconds later). Physical isolation was preserved in substance — `test_suite/` did not yet exist at Step 6's spawn (its first artifacts appeared several minutes later, and `test_helpers/` later still) — and Step 6's prompt additionally carried an explicit hard prohibition on reading `test_helpers/`, `test_suite/`, both design YAMLs, and any sibling task. Step 6 confirmed on exit that it never read them.

Subagent summary (verbatim):

Implementation for `task_2501_commercial_refrigeration_case_manufacturing` is complete and verified.

## Files written
All under `workspace/implementation/`:

- `start.sh` (executable; `cd`s to its own dir, guarded `pip install`, `exec python3 app.py`, honours `$PORT`, default 10000), `requirements.txt`
- `app.py` — app factory, `before_request` auth, `ApiError`/`HTTPException`/`Exception` handlers
- `db.py` (in-memory `Store`, 14 dict collections, logical clock defaulting to `2026-08-01T00:00:00Z`), `response.py` (envelope + list meta), `validation.py`, `serialize.py` (per-entity field order), `errors.py` (all 52 error ids + HTTP codes), `calculations.py` (Decimal/ROUND_HALF_UP formulas), `middleware.py` (9 roles), `services.py` (lookups, counter recomputes, hold cascades)
- `routes/{__init__,catalog,design,testing,plans,logistics,service_network}.py`

Storage is in-memory only; nothing is seeded, preloaded, or persisted. I never read `test_helpers/`, `test_suite/`, the difficulty/corner design files, or any sibling task.

## Endpoints
55 routes across 6 blueprints (mutations + reads/lists for all 14 entities, plus `POST /_clock/set_current_utc`). The full rank 1–39 evaluation ladder is implemented with lowest-rank-wins ordering per endpoint.

## Verification
Booted via `bash start.sh` on port 21438 and ran a 45-assertion end-to-end script covering the whole domain; every expectation matched and the server is now stopped. Highlights:

- Envelope: `meta.api_request_id` = `req_` + 20 uppercase alnum, timestamp with exactly 3 fraction digits + `Z`; list meta carried `limit/offset/total_count/has_more`; immutable reference entities correctly omit `updated_at`/`version`.
- Airflow model: `total_design_load_w` 352.57 from components 215.07/48.0/72.0/17.5/0.0; `installed_charge_grams` 5240, `nameplate_co2e_kg` 621.6, `installed_co2e_kg` 775.5; `curtain_factor`/`velocity_factor` emitted unrounded.
- Test pinning (`pinned_design_revision`, `limit_daily_kwh` 29.2), indices `lab_rated_index` 0.667 / `field_projected_index` 0.746, label pin-through, SoD 403, OCC 412, chamber turnaround conflict 409.
- Pricing 2658180 -> freight 106327 + allowance 66455 -> total 2830962; SoD on approve; release minted serials `S-100-1-1..3` and accrual 73101; QA -> shipment (rank-28 window rejection then success) -> plan auto `COMPLETE`; booking `day_count` 3 / crew `committed_case_days` 9 -> 0 after handoff; handoff rank-34 then rank-3 then success after clock advance.
- Warranty: depot reserve/resolve arithmetic and the plan incurred ledger (54000 -> 80000); revoke cascade REVOKED -> DECERTIFIED.

## Ambiguities resolved
1. **Energy-test start/complete ordering** — the test's own status (rank 7) is checked first, then `pinned_design_revision` staleness (rank 14), then the "model must still be SUBMITTED_FOR_TEST" secondary rank-7, so a test surviving an engineering change reports `ERR_CASE_MODEL_REVISION_STALE` as PRD 3.5 demands.
2. **Handoff order** — shipment resolved first (404), then rank-3 crew identity, then rank-4 body shape; among BOOKED bookings the caller's own crew is preferred and the one containing the logical clock is chosen; none BOOKED -> rank 33, none containing the clock -> rank 34.
3. **Shipment-cancel hops 4/5** gated on hop 3 actually moving the plan COMPLETE->IN_PRODUCTION (literal sequential-hop / silent-no-op reading).
4. **Version bumps** — one increment per row per request (`g.touched_rows`), never one per cascade hop. Counter side effects touch the parent only when the value changes (QA plan counter, incurred ledger); plan `version` always bumps on line add / price / approve / release / shipment create.
5. **Warranty accrual** computed only at release; **incurred** recomputed on claim create/resolve/deny.
6. **Pricing touches each line** (per-line prices are mutations); adding a line touches only the plan.
7. **Rank 24 before 29** for chamber windows (lower rank wins even for an inverted interval); chamber closure applies only when both closure bounds are present, tested as a closed interval.
8. **Client datetimes echoed verbatim**, with parsed copies under `_`-prefixed keys; server-stamped instants formatted to 3 fraction digits.
9. **Unrouted paths and 405s** -> `ERR_NOT_FOUND` 404; malformed JSON -> `ERR_INVALID_REQUEST` 400; unexpected exception -> `ERR_INTERNAL` 500.
10. **Non-schema request fields** (`change_note`, `defect_note`, `cancel_reason`, `release_reason`, `revocation_reason` where not in the entity) are stored but excluded from serialization, so they never leak into responses.

Orchestrator spot-check: the `POST /_clock/set_current_utc` endpoint the implementation added is declared in PRD.md (row present in the 4 Endpoint Definitions table, restricted to `PlatformAdmin`, and described in 2.4 with the `2026-08-01T00:00:00Z` pre-set default), so it is not an untraced capability.

## Step 5: Generate unit tests — 2026-09-03T05:12:00.000Z

(Recorded after Step 6 because Step 5 ran longer; both were launched before either finished.)

Subagent summary (verbatim):

Test generation is complete.

## Files written

`test_helpers/` (9 modules, Stage 1): `__init__.py`, `api_client.py`, `api_errors.py` (52-member `ApiErrorId` + PRD 5 status map registered with the framework validators), `assertions.py` (23 domain assertions), `constants.py`, `factories.py` (16 payload factories), `fixtures.py` (20-step scenario chain + refreshers + action helpers), `test_users.py`, `types.py`.

`test_suite/` (conftest + 12 numbered files, **112 tests**):

| file | tests | concern |
|---|---|---|
| `test_01_case_design.py` | 16 | design creation, geometry/closure/line-set rules |
| `test_02_airflow_and_charge_models.py` | 9 | airflow components, charge bases |
| `test_03_energy_testing.py` | 15 | scheduling pins, lifecycle, index variants, revision pinning |
| `test_04_chamber_scheduling.py` | 6 | turnaround buffer, class/TDA fit |
| `test_05_certification_and_labels.py` | 6 | issuance pins, GWP ceiling, SoD, decert cycle |
| `test_06_store_plan_pricing.py` | 11 | six-step waterfall, tiers, line-add rules |
| `test_07_approval_release_and_holds.py` | 7 | credit ceiling, release, hold vs production, 5-hop cascade |
| `test_08_fabrication_and_qa.py` | 5 | routing, rework/scrap complements, rank-7 priority |
| `test_09_shipments.py` | 7 | manifest, window, OCC, cancel cascade |
| `test_10_install_bookings_and_handoff.py` | 12 | day counts, aggregate capacity, release, handoff |
| `test_11_warranty_and_depot.py` | 7 | coverage boundary, part matching, reservation, denial compensation |
| `test_12_access_control_and_errors.py` | 11 | ranks 1-3, SoD, 404 family, pagination limit |

## Counts and coverage audit

- Queue A (`Design: Difficulty/...`): **37 tests** over all **18** non-stub difficulty instances — every one has **>=2** tests.
- Queue B (`Design: Corner/...`): **75 tests** over all **75** non-stub corner instances — every one has **>=1** test.
- 93 distinct tags = 93 non-stub instances; **zero untranslated non-stub instances**. The **14** `excluded_because:` stubs were correctly not translated.
- Machine-verified: exactly one `Design:` line per test, always the docstring's last line; every tag resolves to a real non-stub instance; **every quoted PRD substring survives a literal whitespace-normalised grep of `workspace/PRD.md`**; the word "scaffold" appears nowhere in emitted code; all files compile and `pytest --collect-only` collects 112 tests with no warnings.

## Instances skipped

None — all 93 non-stub instances passed the two-condition PRD filter.

## Adjudications where the design index contradicted the PRD (implemented per PRD)

1. `Corner/errors/case_model_list_limit_above_maximum_returns_invalid_request` claims HTTP **422**; PRD 2.3 and 2.5 rank 4 both say `ERR_INVALID_REQUEST` is **400**. Asserted 400 (the helper's status map derives it from 5).
2. `Corner/state_machines/compliance_label_issue_pins_index_and_certifies_model` asserts model version **5**, and `Corner/validations/label_issue_with_gwp_above_standard_ceiling_rejected` asserts version **4**; PRD 3.3 makes test completion increment the model's version, so the true values are 6 and 5. Dropped the absolute version assertions in favour of "unchanged from the value captured immediately before the rejected call".
3. `Corner/validations/label_issued_by_submitting_engineer_id_rejected` is impossible as recipe-written (submit-for-test is `DesignEngineer`-only per 4, so a ComplianceOfficer caller dies at rank 2). Implemented the id-based variant: submit with `make_design_engineer_headers("co-001")`, then label as co-001 -> 403 SoD, as co-002 -> 201.
4. `Corner/validations/glass_door_upgrade_on_open_case_rejected` asserts `unit_price_cents 1001500` on the line-add 201; 3.6 says the field is absent until the plan is priced. Asserted absent at add, then 1001500 after pricing.
5. `Corner/cross_cutting_complexity_layers/occ_stale_case_model_version_rejected_on_energy_test_create` asserts the parent's version is still 3 after the *successful* schedule; 2.4 increments it. Asserted 3 unchanged after the 412 and 4 after the accepted create.
6. Minor: PRD 2.5 rank 5's inline enumeration omits `ERR_INSTALL_CREW_NOT_FOUND` and `ERR_PART_INVENTORY_NOT_FOUND`, though both are 5 catalogue rows and both collections expose `GET /{id}` in 4. Kept all ten 404 assertions in `unknown_path_ids_return_entity_specific_not_found` since the code is uniquely derivable from "the entity-specific not-found error at HTTP 404" plus 5.

One helper-side fix made this session: the `TestChamber` TypedDict in `test_helpers/types.py` was renamed `ChamberRow` (and its re-export updated) because the star-import pulled it into every test module and pytest emitted a `PytestCollectionWarning` per file. No other helper changes.

## Step 7: Run tests and iterate — 2026-09-03T05:15:00.000Z

Subagent summary (verbatim):

Clean sweep achieved on the first iteration — no changes were required.

## Summary

**Iterations run:** 1

The 8-round parallel stability sweep was launched under `setsid nohup` as specified (all 8 rounds concurrent, joined with `wait`, no early exit), with `--isolation per-test-server`, and every round ran to completion:

| results file | passed/total | failed | errors | skipped | duration |
|---|---|---|---|---|---|
| results.1.json | 112 / 112 | 0 | 0 | 0 | 220.7s |
| results.2.json | 112 / 112 | 0 | 0 | 0 | 220.6s |
| results.3.json | 112 / 112 | 0 | 0 | 0 | 220.5s |
| results.4.json | 112 / 112 | 0 | 0 | 0 | 220.5s |
| results.5.json | 112 / 112 | 0 | 0 | 0 | 220.5s |
| results.6.json | 112 / 112 | 0 | 0 | 0 | 220.6s |
| results.7.json | 112 / 112 | 0 | 0 | 0 | 220.5s |
| results.8.json | 112 / 112 | 0 | 0 | 0 | 220.5s |

All 8 files verified present on disk at `workspace/implementation/results.{1..8}.json`, each inspected per-test (union of non-`passed` statuses across all 8 rounds is empty). No round showed the reaping signature (no `Terminated` server logs, no mid-request disconnects).

**Tests deleted:** none. The union of failing tests across all 8 rounds was empty, so the diagnostic protocol was never entered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

### Integrity checks run before exiting (to rule out a false-green)
- **No masking markers.** `grep` for `skip`/`xfail` across `test_suite/` and `test_helpers/` returns only two incidental hits — a test *name* and a `Design:` tag containing the word "skips" (`test_08_fabrication_and_qa.py:15,21`, about `OPEN` cases skipping `DOOR_ASSEMBLY` per PRD 3.7). Zero `pytest.mark.skip` / `xfail`; all 8 rounds report `skipped: 0`.
- **No silently uncollected tests.** 113 `def test_` occurrences vs. 112 collected; the one difference is `test_lab_technician_headers` at `test_suite/conftest.py:35`, which is a `@pytest.fixture`, not a test. Collection count therefore matches the true test count of 112.
- **In-memory storage only.** No `sqlite`, `open(`, `json.dump`, `pickle`, `/tmp`, `shelve`, or `redis` anywhere in `workspace/implementation/`, so `start.sh` re-invocation under per-test-server isolation wipes all state.
- **No startup seeding.** The only hits for `seed`/`preload`/`hardcod` are the comment at `workspace/implementation/db.py:3-4` stating the store is empty on every boot.
- **No artifacts edited.** `PRD.md`, `test_suite/`, `test_helpers/` and `implementation/` are byte-unchanged this session; the only files written were the sweep's own `results.*.json` and `workspace/sweep.log`.

One note for the record: the prior pipeline step's worklog documents six adjudications where the scaffold design index contradicted PRD prose (absolute `version` values that ignored PRD-mandated cross-entity bumps, an HTTP 422 claim where PRD 5 says 400, a `unit_price_cents` asserted before pricing, and a role-impossible SoD recipe). Those were resolved in PRD's favour before this step, which is consistent with the PRD-First contract and is the likely reason the suite was already green.

**Orchestrator independent verification** (a first-pass green is exactly the case where a subagent can claim a sweep it never ran, so I re-checked rather than taking the report): parsed all 8 `results.{1..8}.json` myself — every file reports `passed=112 total=112 failed=0 errors=0 skipped=0`. `grep -ci terminated workspace/sweep.log` = 0, so no SIGTERM-reaping signature. 13 files in `test_suite/` (conftest + 12 test modules), matching Step 5's manifest, so no test file was quietly removed.

## Step 8: Finalize PRD — SKIPPED — 2026-09-03T05:16:00.000Z

Skip condition from the skill applied verbatim: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes — zero iterations beyond the baseline. There is therefore no `<step_7_diff>` to hand off and no known PRD-silence site to patch, so no subagent was spawned and `workspace/PRD_FINALIZED.md` is deliberately absent. Step 9 consequently starts from `workspace/PRD.md`.

Judgement call recorded for autonomy: an empty Step 7 diff does NOT mean the PRD is complete — it only means the 112 emitted tests never caught the implementation choosing an interpretation the PRD left open. Every residual silence in this task therefore falls to Step 9, which raises rather than lowers the importance of Step 9's exhaustive scan. To guard against the known Step 9 failure mode (a subagent that copies the source file and returns a summary without actually scanning, leaving the output byte-identical), I am running Step 9 as three sequential file-partitioned passes over `implementation/` instead of one pass, each pass editing the same `PRD_COMPLETED.md` in place, and I will verify a non-trivial diff after each.

## Step 9: Complete PRD — 2026-09-03T06:35:00.000Z

Run as three sequential file-partitioned passes over `implementation/` (orchestrator decision recorded in the Step 8 entry above; the single-pass form is prone to returning a summary without actually scanning, leaving the output byte-identical to its source). Each pass edited the same `workspace/PRD_COMPLETED.md` in place; pass A created it from `PRD.md` (no PRD_FINALIZED.md exists, Step 8 having been skipped). Partition: pass A = cross-cutting layer (app/middleware/response/serialize/errors/validation/db/calculations) + routes/catalog.py + routes/design.py; pass B = routes/testing.py + routes/plans.py; pass C = routes/logistics.py + routes/service_network.py + services.py + the db.py date helpers. Each pass carried an explicit hand-off list to the next so items noticed outside a pass's own partition could not be dropped, and pass C was given all 8 outstanding hand-off items as mandatory.

### Pass A summary (verbatim)

**Line/char counts:** `PRD.md` 451 lines / 92,214 chars -> `PRD_COMPLETED.md` 452 lines / 96,341 chars (**+1 line, +4,103 chars**, 19 lines changed or added). **Counts:** 21 ambiguity-pins, 4 mismatch-revisions (25 discrete changes).

- `2.1` — revise — ambiguity — an empty-string `X-User-ID`/`X-User-Role` is treated as absent (401) — `middleware.py:42`
- `2.2` — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alphanumeric chars — `response.py:13-14`
- `2.2` — revise — ambiguity — single-resource `meta` carries only the two envelope fields — `response.py:17-33`
- `2.2` — insert — ambiguity — unknown path / wrong method -> `ERR_NOT_FOUND` 404, produced by routing *before* rank-1 auth — `app.py:37-40`, `middleware.py:31`
- `2.3` — revise — ambiguity — non-integer `limit`/`offset` -> 400; empty-string param = omitted -> default — `validation.py:171-186`
- `2.3` — insert — ambiguity — same-`created_at` rows tie-break on creation sequence — `db.py:64-66`
- `2.3` — insert — ambiguity — filters combine conjunctively; enum filters validated (400); identifier filters opaque — `validation.py:189-202`, `routes/design.py:270-281`
- `2.4` — insert — ambiguity — a row mutated more than once in one request still advances `version` by exactly 1 — `services.py:29-41`
- `2.4` — **revise — mismatch** — "never reads wall-clock time" was false: `created_at`, `updated_at`, `api_request_timestamp` are host readings; only comparisons and `handoff_at`/`warranty_start_date` use the logical clock — `db.py:35-36`, `response.py:20`, `logistics.py:228`
- `2.4` — insert — ambiguity — the clock accepts any instant and may be rewound — `catalog.py:221-227`
- `2.4` — insert — ambiguity — ISO parsing (naive = UTC, offsets converted, date-only = midnight UTC); client timestamps echoed verbatim — `validation.py:142-156`, `catalog.py:93-95`
- `2.5 rank 3` — **insert — mismatch** — the path shipment is resolved *before* the crew-identity test, so an unknown shipment id on handoff reports `ERR_SHIPMENT_NOT_FOUND` (404), not 403 — `logistics.py:198-203`
- `2.5 rank 4` — insert — ambiguity — unparseable/non-object body fails at rank 4; JSON `null` counts as absent; undeclared fields ignored — `validation.py:17-30`
- `2.7` — revise — ambiguity — a stray version field elsewhere is *ignored*, not rejected — `validation.py:29-30`
- `3.1` — revise — ambiguity — `refrigerant_code` <= 32 chars — `catalog.py:52`
- `3.1` — **revise — mismatch** — `allowed_system_types` is "a non-empty array drawn from" (duplicates not rejected) — `catalog.py:57`, `validation.py:115-139`
- `3.1` — revise — ambiguity — `max_gwp` is an integer >= 1 — `catalog.py:82`
- `3.1` — **revise — mismatch** — `chamber_code` <= 32 chars; `supported_temperature_classes` is an array drawn from HT/MT/LT, not a subset — `catalog.py:109-112`
- `3.1` — revise — ambiguity — a chamber declaring only one closure boundary has no closure at all — `catalog.py:116-131`, `testing.py:160-167`
- `3.1` — revise — ambiguity — `crew_code` <= 32 chars; region codes only required non-empty, matched by exact string equality — `catalog.py:141-143`, `logistics.py:303`
- `3.2` — revise — ambiguity — `model_code` <= 32 chars — `design.py:110`
- `3.2` — revise — ambiguity — `predecessor_model_id`, when supplied, must resolve to an existing case model — `design.py:132-133`
- `3.2` — revise — ambiguity — `line_set_length_ft` is a whole number >= 0 — `design.py:119`
- `3.2` — insert — ambiguity — a `MODELED` model with absent `total_design_load_w` fails the transition itself (`ERR_INVALID_STATE_TRANSITION` 409) — `design.py:200-202`
- `3.5` — revise — ambiguity — `change_note` required and non-empty, stored but not in the case-model response shape — `design.py:220`, `serialize.py:24-35`

Verified-correct and deliberately unchanged in pass A's half: the whole airflow/charge model (all coefficients, floors, rounding order, the `SELF_CONTAINED` 0.08 rejection term computed off the already-rounded subtotal, the unrounded `curtain_factor`/`velocity_factor`, the 26 g/ft installed basis, both CO2e bases at 1 dp) matches `calculations.py:50-103` exactly; rank order in `create_case_model` (6 -> 17 -> 18 -> 21); rank-10 guarding only airflow + engineering change; rank-17 guarding creation + airflow; rank-18 guarding creation + engineering change; hop-1 field clearing (11 fields); the 4 table and the 5 catalogue rows for that half.

### Pass B summary (verbatim)

**Before:** 452 lines, 96,341 chars. **After:** 452 lines, 100,213 chars (+3,872). Structure untouched; both 4/5 tables byte-identical. **Ambiguity-pins: 16, mismatch-revisions: 3** (13 in-paragraph edit operations across 3.3, 3.4, 3.6, 3.7).

- `3.3` — insert — ambiguity — `test_ambient_c`/`store_ambient_c` carry no sign or magnitude restriction — testing.py:72-73
- `3.3` — insert — ambiguity — scheduling imposes **no** case-model `status` precondition; a test may be booked against a `DRAFT` design — testing.py:65-116
- `3.3` — insert — ambiguity — a new test's six measured/computed fields are absent until completion — testing.py:132-137
- `3.3` — insert — ambiguity — the chamber-closure comparison uses the candidate's *bare* interval (no turnaround buffer); `window_end` equal to `closed_window_start` is accepted — testing.py:160-167
- `3.3` — insert — ambiguity — on start, rank-14 revision check precedes the `SUBMITTED_FOR_TEST` precondition, so an engineering-changed model yields `ERR_CASE_MODEL_REVISION_STALE` — testing.py:181-186
- `3.3` — insert — ambiguity — same precedence on complete — testing.py:205-209
- `3.4` — insert — ambiguity — `label_code` is a non-empty string of up to 32 characters — testing.py:265
- `3.4` — insert — ambiguity — the named test must belong to the named model, else rank-7 `ERR_INVALID_STATE_TRANSITION` — testing.py:274-276
- `3.4` — revise — ambiguity — rank-12 GWP is read from the case model's **current** `refrigerant_id` — testing.py:288-294
- `3.6` — revise — **mismatch** — `region_code` is not validated as two letters; only a non-empty string, matched later by exact equality — plans.py:99
- `3.6` — insert — ambiguity — `credit_limit_cents` is an integer of at least zero — plans.py:102
- `3.6` — insert — ambiguity — the remodel window is exempt from the rank-29 interval rule — plans.py:100-101
- `3.6` — insert — ambiguity — `length_ft` must be 4/6/8/12 at **rank 4** (`ERR_INVALID_REQUEST`), not rank 19 — plans.py:144
- `3.6` — insert — ambiguity — `merchandising_options` admits duplicates, stored as supplied, each occurrence charged — plans.py:147-149, calculations.py:167
- `3.6` — insert — ambiguity — on `PRICED -> DRAFT` revert the lines keep their stale `unit_price_cents`/`extended_price_cents` — plans.py:191-195
- `3.7` — revise — **mismatch** — removed the "requesting the branch that does not match the door type" claim (the API offers no such choice); the branch is server-chosen and `DOOR_ASSEMBLY -> FINAL_QA` is unconditional — plans.py:342-344
- `3.7` — insert — ambiguity — advance is a dead end from `FINAL_QA`, `COMPLETE`, `HELD`, `SHIPPED`, `SCRAPPED` — plans.py:347-348
- `3.7` — insert — ambiguity — `defect_note` defaults absent, must be non-empty when supplied, retained on all three outcome paths, not in the response shape — plans.py:359,373-374; serialize.py:68-73
- `3.7` — insert — **mismatch** — the plan's `version` advances only when the recomputed `units_completed_count` actually changes, i.e. only on `PASS` — plans.py:386-390

Pass A integrity confirmed intact: all 19 of pass A's diff hunks still divergent from `PRD.md`, none overlapping a pass-B line.

### Pass C summary (verbatim)

| | lines | chars |
|---|---|---|
| original `PRD.md` | 451 | 92,214 |
| `PRD_COMPLETED.md` before pass C | 452 | 100,213 |
| `PRD_COMPLETED.md` after pass C | 452 | 105,158 |

15 lines touched (0 added/removed); diff versus `PRD.md` now exactly 46 changed lines = 31 from passes A/B (all still present) + 15. **8 ambiguity-pins, 7 mismatch/factual-error revisions.**

- 2.1 — revise — factual error — "the readiness test described in 3.9" -> 3.8 (error present in the original PRD)
- 2.10 — revise — mismatch — "a booking whose `end_date` is a given day does not occupy that day" is false for a time-carrying end; qualified to "is midnight on a given day" with a pointer to 3.8 — `db.py:98-105`
- 3.8 — insert — ambiguity — `ship_date` carries no window constraint of its own; creation imposes no `production_status` precondition — `logistics.py:87-91`
- 3.8 — insert — ambiguity — a loaded unit whose originating line cannot be resolved contributes zero feet to `linear_feet` — `logistics.py:96`
- 3.8 — insert — ambiguity — the production promotion is available **only** out of `IN_PRODUCTION` — `logistics.py:120-122`
- 3.8 — insert — ambiguity — `DELIVERED`/`HANDED_OFF`/`CANCELLED` are advance dead ends (rank-7 409) — `logistics.py:134-137`
- 3.8 — revise — mismatch — cancel cascade: hop 3 moves the plan only when it currently reads `COMPLETE` **and** the count fell below `unit_count` (plan `version` bumped either way); hops 4/5 fire only when that move happened, otherwise silent no-ops leaving bookings `BOOKED` and crew commitment unchanged; hop 2 guards on unit status `SHIPPED`; `cancel_reason` retained internally, not in the response shape — `logistics.py:157,161-190`
- 3.8 — revise — mismatch — booking day set/`day_count`: start truncated to its whole UTC calendar day, plus every later day whose midnight precedes `end_date`; computed once at creation. Plus: no compliance-hold check and no shipment-status precondition, so a booking may be made against a `HANDED_OFF` or `CANCELLED` shipment or a plan with held lines — `logistics.py:290-332`, `db.py:98-105`
- 3.8 — insert — ambiguity — the capacity scan derives each existing booking's days by the same truncating rule and spans all of the crew's `BOOKED` bookings across every shipment, plan and region — `logistics.py:309-318`
- 3.8 — insert — ambiguity — `release_reason` retained internally, not part of the booking's response shape — `logistics.py:354`, `serialize.py:84-88`
- 3.8 — revise — mismatch — rank 33 satisfied by a `BOOKED` booking held by *any* crew; rank 34 asks whether *one of* them contains the clock; the acting booking is chosen deterministically (own crew's `BOOKED` bookings first in `created_at` order, then other crews', first window hit wins) — `logistics.py:212-226`
- 3.8 — revise — mismatch — the selected booking (possibly another crew's) is the one moved to `COMPLETED`, and it is *its own* crew whose `committed_case_days` drops; every other `BOOKED` booking is untouched — `logistics.py:234-241`
- 3.9 — insert — ambiguity — the claim's `install_crew_id` is unconstrained beyond rank-6 existence — `service_network.py:76`
- 3.9 — revise — ambiguity — coverage end advances whole calendar months keeping day-of-month and time-of-day, **clamped back** to the target month's last day when it has no such day (29 Feb + 12 months -> 28 Feb); no routing-status precondition on the claimed unit — `db.py:81-91`, `service_network.py:90-95`
- 3.9 — revise — mismatch — ledger: both halves written together only at plan release and the accrual half never recomputed thereafter (a later scrap does not reduce it); the three claim events recompute the **incurred half only** and bump the plan's `version`/`updated_at` only when the incurred figure actually changes; reserving parts recomputes neither half and never touches the plan — `service_network.py:52-58,117,173,202`, `plans.py:287-289`

All 8 mandatory hand-off items dispositioned: (1) `add_months` clamping pinned in 3.9; (2) `occupied_days` truncation pinned in 3.8 twice, and 2.10's now-inaccurate sentence corrected; (3) handoff booking selection pinned in the rank-34 paragraph and the "writes four things" paragraph; (4) `cancel_reason`/`release_reason` non-serialization pinned in both places; (5) cancel hops 4/5 conditionality pinned including the no-op branch; (6) promotion only from `IN_PRODUCTION` and missing-line-as-0-ft both pinned; (7) booking creation's absent hold check and absent shipment-status precondition pinned (2.8's four-operation hold list and 2.5's rank-7 list already excluded booking creation, so no change needed there); (8) `_refresh_ledger` conditional bump and incurred-only recompute pinned in 3.9.

Pass C's whole-document sanity check: (a) ends at the 5 table, final row `ERR_CREDIT_LIMIT_EXCEEDED | 402`; (b) 52 endpoint rows and 52 error rows intact, neither table edited; (c) all 31 pass-A/B changed lines still present; (d) no difficulty/scaffold/test-harness/pipeline language (grep clean); (e) heading list byte-identical to `PRD.md`, nothing renumbered, dropped or reflowed.

### Orchestrator verification of Step 9

- `PRD_COMPLETED.md` is 452 lines / 105,158 chars vs `PRD.md` 451 / 92,214 — **not** byte-identical (`cmp` differs), so the scan demonstrably ran; 46 changed lines, +12,944 chars across the three passes (25 + 19 + 15 = 59 discrete changes; 45 ambiguity-pins, 14 mismatch/factual-error revisions).
- Heading list diffed clean against `PRD.md`; 54 pipe-rows in each of 4 and 5 (52 data rows + header + separator), so no endpoint or error row was lost.
- Tail confirmed at `| ERR_CREDIT_LIMIT_EXCEEDED | 402 |` — complete, not truncated.
- `grep -ci "scaffold|pytest|test_suite|difficulty|harder than expert"` = 0, so nothing about the pipeline or the difficulty instruction leaked into the deliverable PRD.
- `PRD_FINALIZED.md` correctly absent (Step 8 skipped).
- No `.py` file under `implementation/`, `test_suite/` or `test_helpers/` is newer than `results.8.json`, so the recorded 8/8 green sweep still describes the code as it stands; Step 9 touched only `PRD_COMPLETED.md`.

Pipeline complete through Step 9.
