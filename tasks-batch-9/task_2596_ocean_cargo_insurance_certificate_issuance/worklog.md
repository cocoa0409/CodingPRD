# Worklog — task_2596_ocean_cargo_insurance_certificate_issuance

## Step 1: Create task directory — 2026-09-03T16:36:04.268Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2596_ocean_cargo_insurance_certificate_issuance` and its `workspace/` subdirectory. Index 2596 was pre-assigned by the orchestrating prompt; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T18:33:30.616Z

All three artifacts are complete and the linter is clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2596_ocean_cargo_insurance_certificate_issuance/`
- `SCAFFOLD.yaml` — 3362 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2023 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5019 lines

(The directory also holds a pre-existing `worklog.md` and empty `workspace/` that I did not touch.)

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2596_ocean_cargo_insurance_certificate_issuance/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2596_ocean_cargo_insurance_certificate_issuance/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2596_ocean_cargo_insurance_certificate_issuance/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  1105

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Counts

SCAFFOLD.yaml (§1.0–§1.7): 13 entities, 12 state machines (parallel shape: OpenPolicy and Certificate each carry a status axis plus an independent war_cover_status axis; ClaimFile carries status plus subrogation_status), 2 concurrency rules, 10 calculations (2 dual-variant), 34 validation rules spanning priorities 1–31, 56 endpoints, 45 errors, 7 roles. Top-level keys contain neither `scaffold_difficulty_design` nor `scaffold_corner_design`.

§1.8: 9 rule_ids × 2 instances = 18 (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

§1.9: 9 sections, 74 instances = 56 full `test_recipe`s + 18 `excluded_because` stubs. Per section: entities 10, state_machines 13, calculations 13, validations 16, endpoints 4, errors 4, rbac 7, cross_cutting_complexity_layers 5, consistency_model 2. Every stub cites a distinct §1.8 instance, so the 18 stubs map one-to-one onto the 18 difficulty instances (verified: no unresolved, no duplicated, no uncited). All 45 error ids are triggered somewhere across the two design files, including both 412s via the two OCC recipes.

## Design adjudications

- **Added `GET /ports` to §1.5** (priority-ladder step 2). Port was the only entity with a create + item read but no list endpoint, and three §1.9 recipes (pagination-bounds rejection, unknown-role refusal, shared Underwriter/ComplianceOfficer port creation) needed a list read. Endpoint count went 55 → 56.
- **Pagination captures relocated to `$.meta`**: for `Entity[]` outputs `data` is the array, so `total_count`/`has_more` cannot live under `$.data`. All 21 such captures now read `$.meta.total_count` / `$.meta.has_more`, matching §1.0's `pagination_fields`.
- **Re-pointed one stub** so the two `resource_temporal_overlap` instances are cited once each: the calculations `interval_merge` stub became `storage_window_interval_adjacency_corner` citing the half-open port-storage-window instance, leaving the surveyor closed-interval instance to the errors-section stub.
- **Backfilled `distinguishing_aspect`** on 8 early stubs that carried only `grounds` + `excluded_because`, so all 74 instances satisfy the per-instance contract.
- **Logical-clock precondition fix**: the "large claim needs a survey report" recipe called `file-report` while the clock was still at the 2026-08-01 default, which violates `clock >= window_start_at`; a `POST /_clock/set_current_utc` was inserted ahead of it.
- **GA ordering adjudication**: `POST /ga-events` puts the vessel in GA_HOLD, and priority 11 (`ERR_VESSEL_BLOCKED`) then blocks any issue, so every GA recipe issues its certificates *before* declaring the event; the "no contributing certificates" leg is produced by a mismatched `voyage_sailing_date` plus a DRAFT certificate rather than by withholding issuance.
- **War-reinstatement consistency**: the state_machines recipe de-escalates NLRTM back to AMBER before reinstating (priority 10 satisfied), while the errors recipe deliberately reinstates while the port is still LISTED_AREA to get the 409 — the two are non-contradictory by construction.
- Earlier sessions applied 16 self-consistency fixes inside SCAFFOLD.yaml (validation-ladder gaps, missing derived fields, cascade wording) before the design files were written.

## Step 3: Copy shared files — 2026-09-03T18:33:30.616Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T18:50:00.000Z

Orchestrator truncation check: `wc -l -c` = 458 lines / 98602 bytes; `tail -12` ends on the final row of the §5 error table (`| ERR_RECOVERY_EXCEEDS_SETTLEMENT | 422 |`) — a genuine section boundary. Heading scan shows §1, §2.1–§2.11, §3.1–§3.9, §4, §5 all present. No regeneration needed.

Subagent summary (verbatim):

All remaining sections are written and all three Hard Contracts pass.

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2596_ocean_cargo_insurance_certificate_issuance/workspace/PRD.md` — 458 lines, 98,602 bytes. `tail -30` shows the file ending at the last row of the §5 error table (`| \`ERR_RECOVERY_EXCEEDS_SETTLEMENT\` | 422 |`) — a genuine section boundary, not mid-sentence. No truncation; every section was appended via chunked heredocs.

**Structure (all scaffold sections covered):**
- §1 Introduction; §2 with 11 subsections (2.1 RBAC → 2.11 Ledger Consistency), inside the 8–12 requirement; §3 with 9 freely-grouped subsections (3.1 Open Cover → 3.9 General Average), inside the 5–9 requirement; §4 endpoint table; §5 error catalogue.
- Sections completed this stretch: §3.9 (GA declaration, vessel `GA_HOLD` cascade, the full `ga_contribution_allocation` waterfall with the 93049.60 / 64450.40 → 157500.00 residual example and the 18609.92 / 12890.08 deposits, security posting with OCC, four-link finalisation), §4, §5.

**Contract 1 — Field-Name Coverage: PASS.** Two independent passes. Pass A (YAML walk of every `entities[].fields[].name`, `request_body`, `input`, `query_params`, `path_params`): 159 distinct identifiers, 0 missing from PRD backticks. Pass B (textual line scan of the scaffold, optional-`?` suffixes stripped): 161 candidates, 0 field misses — the only 10 unmatched tokens were the 10 `calculations[].name` labels (`certificate_insured_value`, `ga_contribution_allocation`, etc.), which are calculation ids, not fields, and are deliberately expressed as prose rather than named symbols.

**Contract 2 — Rule Coverage: PASS.** All 45 error ids appear in §1–§4 prose, not merely in the §5 table (verified by excluding the catalogue from the search text). All 34 validations (priorities 1–31, including the shared-priority pairs at 6, 8 and 9) are present in the documented refusal order — spot-verified against scaffold priority order for the §3.3 declaration band (7 → 8 → 12 → 14 → 17 → 18) and the §3.8 appointment band (25 window conflict → 26 certification → 27 inactive). All 12 state machines and every state literal across them appear verbatim (0 missing). All 10 calculations, both `concurrency_rules`, and every named constant value are present (0 missing). Cross-entity side effects spot-checked against the scaffold's `side_effects` blocks, including the non-obvious ones: `auditor_user_id` cleared on re-submission, `booked_minutes_total` *not* reduced on report filing, the conditional `SURVEY_ORDERED → OPENED` reversion on appointment cancellation, `overage_surcharge_pct` preserved through `GA_HOLD`, and all 99 field defaults/initial values.

**Contract 3 — §3 Path Purity: PASS.** Scanned lines 162–344 (§3 body): 0 backtick tokens starting with `/`, 0 bare HTTP methods, 0 method+path combinations, and 0 plain-text method+path occurrences outside backticks. Paths appear only in §2 and the §4 table.

**Additional checks:** §4 table matches the scaffold exactly — 56 endpoints (55 business + `POST /_clock/set_current_utc`), 0 extra, 0 missing, and 0 role-list mismatches across all 56 rows. §2.2 is byte-identical to `section-2.2-response-structure.md` (only a trailing blank-line separator differs). No pseudocode or operator syntax (`==`, `<=`, `round(`, `if (`) anywhere. One fuzzy word was found and fixed: "deliberately conservative" → "deliberately strict" in the survey-window paragraph.

**Scaffold contradictions resolved by explicit decision** (each documented as a pinned rule in the prose so the implementer has no discretion): endorsement raises `aggregate_premium_booked` by the replacement's premium only (never reduced — matched the twice-asserted invariant and the field's own description, over the §1.5 "adjusted by difference" note); the transit sweep exempts `CLAIMED` certificates only while the claim is pre-adjustment, reconciling `transit_termination_instant.input_set` with the `CLAIMED → TRANSIT_ENDED` transition; `ERR_WAR_COVER_TERMINATED` on reinstatement is pinned to the port in `war_termination_port_unlocode` still being `LISTED_AREA`; the capacity tower is ordered by validation priority (commodity share before per-certificate limit), not by the calculation's formula order; and `SURVEY_WINDOW_MIN_MINUTES` (30) is stated as a business fact rather than invented as a rejection rule, since no field constraint declares it.

I did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task directory, and no report/summary `.md` files were created.

## Step 6: Generate implementation — 2026-09-03T19:30:25.000Z

The implementation is complete and verified. Final report:

## Deliverables

`/home/ubuntu/github/CodingPRD/tasks/task_2596_ocean_cargo_insurance_certificate_issuance/workspace/implementation/`

| File | Lines |
|---|---|
| `app.py` | 65 |
| `clock.py` | 49 |
| `errors.py` | 96 |
| `response.py` | 44 |
| `routes_certificates.py` | 444 |
| `routes_claims.py` | 393 |
| `routes_ga.py` | 188 |
| `routes_premium.py` | 160 |
| `routes_registry.py` | 362 |
| `serialize.py` | 293 |
| `services.py` | 526 |
| `store.py` | 65 |
| `validation.py` | 283 |
| `requirements.txt` | 1 |
| `start.sh` | 10 (executable) |
| **total** | **2979** |

**Endpoints: 56/56** — Flask registers exactly 56 rules (excluding `static`), matching the 56 `- method:` entries in SCAFFOLD.yaml, including `POST /_clock/set_current_utc`.

**Storage:** in-memory dicts only. Re-verified just now — no `sqlite`, no `open(`, no `/tmp`, no `json.dump` anywhere in the tree; the only matches for "seed/preload/hardcode" are the `store.py` docstring stating the store starts empty. No entity data is created at import or boot.

**Smoke test:** three sequential fresh boots on port 17596, each ready in ~700 ms, store provably empty (`GET /ports` -> `total_count: 0`, `data: []`). Killed by PID/port only; `lsof -tiTCP:17596 -sTCP:LISTEN` confirms the port is free. No broad `pkill` was ever issued. Temp smoke artifacts and `__pycache__` removed.

**PRD worked examples all reproduce exactly:** insured value 1155000.00; effective rate 4.7250; premium 5457.38 + 693.00 + 294.53 = 6444.91; transit termination 2026-10-05T00:00:00Z; cancellation returns 6444.91 / 3222.46; endorsement replacement 6696.00; LISTED_AREA war return 1026.00; reinstatement 600.00; GA fee 7500.00, allowance 157500.00, TCV 1955000.00, rate 0.080563, contributions 93049.60 / 64450.40, deposits 18609.92 / 12890.08; claim 141875.00 less 2500.00 deductible; time bar 2027-09-05; net loss 91875.00 after a 50000 recovery. Refusal precedence spot-checked across the 401/403/400/404-path/404-body-ref/409-dup/409-state/412/422 bands plus `ERR_ALREADY_TERMINAL` and all four capacity-tower errors.

## Adjudications

1. `created_at`/`updated_at`/`api_request_timestamp` all read the logical clock; it never falls back to wall time.
2. List ties (identical `created_at`) broken by an internal monotonic `_seq`.
3. Limit-tower consistency and `expiry_at > inception_at` are enforced at **activate** as `ERR_INVALID_STATE`, not at create.
4. `run-transit-sweep` is permitted in any policy status.
5. `reinstatement_rate_per_mille <= 0` at reinstate -> `ERR_INVALID_STATE`.
6. `loss_date`-inside-cover and the WAR/STRIKES peril-in-force rule are **not** enforced — no error id and no validations row exists for either.
7. GA postings are created in contributor `created_at` ASC order; the rounding residual lands on the first bucket of (insured_value DESC, created_at ASC).
8. `certificates_issued_count` is not incremented by an endorsement.
9. Ownership is not enforced on GET reads.
10. Missing measurement inputs at adjust -> `ERR_INVALID_REQUEST` raised inside the final branch, so the DENIED path stays reachable.
11. GA event `version` increments even when the same request also completes SECURITY_COMPLETE.
12. The war-risk-tier cascade bumps the policy `version` once for the whole cascade.
13. `file-report` does not reject a claim that is not SURVEY_ORDERED; the cascade simply does not move the status.
14. Stamping `premium_declaration_id` bumps the certificate `version`.
15. Accumulation ledger rows bump `version` per movement (so +2 on one port when loading == discharge).
16. Declaration initial values follow the entity defaults (nulls for totals, zeros for counts).
17. `ga_event_id` is stored only when `loss_type == GENERAL_AVERAGE`.
18. Date-only strings are accepted and normalised; non-midnight voyage dates -> `ERR_VOYAGE_DATES_INVALID`.
19. Money and rates serialise as JSON numbers from quantized `Decimal`s.
20. `confirm-delivery` **does** enforce Assured ownership (PRD wins over the scaffold's priority-6 list).
21. `endorse` re-tests packaging, voyage dates, valuation and commodity share only — not the full capacity tower.
22. `war_premium_amount` stays 0.00 unless the war axis attaches; strikes premium is computed whenever requested, with no port multiplier.
23. `max_conveyance_share_pct`, `survey_required_above_amount`, `salvage_award_amount` treated as optional per their PRD defaults, despite the scaffold omitting `?`.
24. `cancellation_reason`, `delivered_at`, `audit_note` are accepted and stored internally but not serialised — SCAFFOLD §1.1 lists them only as endpoint inputs, never as entity fields.
25. `delivered_at` pulls `transit_termination_at` back only when explicitly supplied.
26. Declaration `period_end <= period_start` -> `ERR_INVALID_REQUEST` 400.
27. Survey window bounds (30..480 minutes, end > start) -> `ERR_INVALID_REQUEST` 400.
28. Declaring a GA event always increments `open_ga_event_count`, but moves the vessel to GA_HOLD only from APPROVED|OVERAGE_SURCHARGED.
29. `endorse` enforces `certificate_number` uniqueness (`ERR_DUPLICATE_REFERENCE`) at the priority-7 position even though the scaffold's `applies_to` omits it.
30. `invoice_value`/`declared_value` are schema-validated as `>= 0` so the `> 0` requirement surfaces as `ERR_VALUATION_INPUT_MISSING` 422 rather than a 400.

One PRD-vs-scaffold conflict worth flagging to the caller: on endorse, `aggregate_premium_booked` rises only by the replacement certificate's total and is never reduced (PRD text), while `aggregate_insured_value_booked` moves by the delta `(new - old)`; the original's premium is returned via `aggregate_return_premium` instead.

## Step 5: Generate unit tests — 2026-09-03T19:40:47.000Z

(Steps 5 and 6 ran concurrently; Step 6's entry above was written first only because that agent exited first.)

Test generation for task 2596 is complete.

## Output (both at the task root, nothing inside `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2596_ocean_cargo_insurance_certificate_issuance/test_helpers/` — 1,774 lines / 9 files:
`__init__.py` 133, `api_client.py` 279 (exactly 56 endpoint methods), `api_errors.py` 119 (all 45 error ids + HTTP status map registered via `set_error_http_status_map`), `assertions.py` 212, `constants.py` 256, `factories.py` 340, `fixtures.py` 333 (15 composite builders + 9 pytest fixtures), `test_users.py` 79, `types.py` 23.

`.../test_suite/` — 9,326 lines / 16 files: `conftest.py` 24 plus
`test_01` 318 · `test_02` 385 · `test_03` 338 · `test_04` 436 · `test_05` 585 · `test_06` 575 · `test_07` 418 · `test_08` 838 · `test_09` 969 · `test_10` 859 · `test_11` 790 · `test_12` 876 · `test_13` 852 · `test_14` 604 · `test_15` 459.

## Test count and queue breakdown

**238 tests** (collected cleanly by `pytest --collect-only`: 238, no import or fixture-name errors; no server was started, no test was executed).

- **Queue A (difficulty index): 69 tests, 18/18 instances, every one >=2 tests.** Files 01–07: certificate valuation and premium rounding, claim indemnity plus the resurvey cycle, GA fee/allocation and the finalisation release cascade, the two war-risk axes and the four-link listed-area cascade, the two priority pairs and two precision boundaries, cross-entity gates and temporal overlap, the two compensating invariants.
- **Queue B (corner index): 169 tests, 56/56 non-stub instances, every one >=1 test.** Files 08–15: entities 26, state machines 30, calculations 21, validations 24+21, endpoints+errors 21, rbac 16, concurrency+consistency 10. None of the 18 `excluded_because:` stubs was translated.

## Mechanical audit — 0 problems

Every test: exactly one `Design:` line, as the last docstring line, resolving to a real non-stub instance (no untagged, dual-tagged or dangling tags); a verbatim >=8-word PRD sentence above it, machine-verified as an exact substring of `workspace/PRD.md`; >=5 tests per file; no `scaffold`/`§`/section references anywhere in `test_suite/` or `test_helpers/`; no `skip`/`xfail`, no `time.sleep`, no random data, no `validate_error_is_one_of` fallbacks (0 uses — every refusal is pinned to one error id).

## Instances skipped: none

All 74 non-stub instances passed the PRD-first filter. Sub-assertions were dropped (never weakened, never faked) where the PRD does not uniquely derive them — notably: `expiry_at <= inception_at` at policy creation (PRD pins that refusal only at activation); `GET /surveyors/{unknown}` (surveyor-not-found is pinned only as a body-reference error, so it is asserted there instead); GA `postings_required_count` at `DECLARED` ("zero or null"); the defaulted `travel_buffer_minutes` read-back; premium on early delivery; policy `version` on a non-expiring sweep; and `settled_by_user_id` before settlement.

## PRD-vs-index divergences (PRD followed in every case)

1. **Endorsement aggregate** — the index asserts `aggregate_premium_booked == 7672.51`; the PRD says the ledger rises by the replacement's premium and is never reduced, so the test asserts **14117.42**.
2. **`packaging_code: "PALLET_SHRINKWRAP"`** is not a declared enum value, so it would be refused at schema validation before the warranty rule it was meant to demonstrate; replaced with the valid-but-mismatching `STD` against a required `EXPORT_CRATE`.
3. **`classification_society: "BV"`** is a *valid* society, so it cannot yield `ERR_INVALID_REQUEST`; the enum rule is tested with `RINA`.
4. **Empty-payload `confirm-delivery`** pull-back of `transit_termination_at` is undocumented; the test passes `delivered_at` explicitly for the same asserted outcome.
5. Timestamp equality is asserted on parsed instants where the PRD pins the instant but not the fractional-second rendering, and two listing assertions compare sets rather than positions because all rows share one logical-clock `created_at`.

Note: the Step 6 implementation agent is still running; nothing under `workspace/implementation/` was read or written, and `SCAFFOLD.yaml` was not walked for test material.

## Step 7: Run tests and iterate — 2026-09-03T20:11:55.000Z

Orchestrator verification (independent of the subagent's claim): all 8 `workspace/implementation/results.$i.json` exist, each reports `passed=238 total=238 failed=0`; `grep` finds 0 `pytest.mark.skip`/`xfail` in `test_suite/`; test count 238.

Subagent summary (verbatim):

Clean exit. All 238 tests pass in all 8 parallel rounds.

## Summary

**Iterations run:** 2

- Iteration 1: 16 failures, identical in all 8 rounds (fully deterministic — no flakiness, no load-induced timeouts, no connection resets).
- Iteration 2: 238/238 passed in all 8 rounds.

**Tests deleted:** none. Every failure traced to a test-artifact bug in one of two families; each asserted rule is verbatim in PRD.md and uniquely derivable, so nothing qualified for deletion.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — added `parse_instant()` / `assert_instant()`: compare ISO 8601 UTC timestamps as instants. PRD §2.4 pins three fractional digits only for `created_at`/`updated_at`; for business instants (`attachment_at`, `transit_termination_at`, `time_bar_at`, `subrogation_notice_at`, `window_start_at`/`window_end_at`, `period_start`, `sailing_date`) PRD prose writes bare `...T00:00:00Z` while pinning the *moment*, not the rendering — so raw-string equality was not a PRD-derivable assertion, but instant equality is (and is equally strict). This promotes the `_assert_instant` convention already used locally in `test_08`/`test_10`.
- `test_helpers/__init__.py` — exported `assert_instant` / `parse_instant`.

**Fixes applied to `test_suite/`:**
- Timestamp-rendering family (12 failures, 32 comparison sites converted to `assert_instant` across `test_02`, `test_06`, `test_07`, `test_11`, `test_12`, `test_13`, `test_15`). The implementation renders every timestamp uniformly with `.000Z`, which PRD §2.4 mandates for the system-managed fields; the tests compared against bare-`Z` literals. Latent sites that happened to pass were converted too, so the same bug cannot resurface.
- Role-header family (4 failures, `test_suite/test_11_underwriting_validation_rules.py`) — `test_the_commodity_share_ceiling_refuses_the_line_at_declaration`, `test_a_second_line_on_the_same_conveyance_breaks_the_conveyance_limit`, `test_a_later_sailing_date_opens_a_fresh_conveyance_bucket`, `test_the_annual_aggregate_stops_a_third_conveyance` and the shared `_issue_line` helper were declaring shipments with `UNDERWRITER` headers. PRD §4 lists `POST /certificates` as **Assured**-only and §3.3 states "Declaration is the assured's act, not the underwriter's", so the implementation's `ERR_UNAUTHORIZED` 403 was correct; switched to `env["assured"]` (which `test_helpers.factories.create_certificate` already defaults to).

**Fixes applied to `implementation/`:** none. No PRD-required check was removed or weakened, and no `git`-tracked implementation file was modified — every failure was a test-artifact defect.

No `skip`, `xfail`, or `validate_error_is_one_of` relaxations exist anywhere in `test_suite/`; test count is unchanged at 238.

## Step 8: Finalize PRD — 2026-09-03T20:20:54.000Z

Step 8 was NOT skipped: Step 7 ran 2 iterations with non-zero `test_helpers/` and `test_suite/` fixes (0 implementation fixes), so the skip condition (all four counts zero) did not hold.

Orchestrator verification: PRD.md 458 lines / PRD_FINALIZED.md 460 lines; tail confirms the file still ends at the final row of the §5 error table.

Subagent summary (verbatim):

PRD_FINALIZED.md is written with a single, minimal insertion.

**Line counts:** PRD.md 458 → PRD_FINALIZED.md 460 (+2 lines, +0.44%). Ends at the final `ERR_RECOVERY_EXCEEDS_SETTLEMENT | 422` row of the §5 error table. Only difference vs PRD.md is the one inserted paragraph (verified by `diff`).

**Changes**

- §2.4 Common Resource Properties — insert — one paragraph pinning that *every* instant in a response body (not just `created_at`/`updated_at`) is rendered as ISO 8601 UTC with exactly three fractional digits, that unset instant fields are `null`, and that prose spellings like `2026-09-05T00:00:00Z` elsewhere in the document name the moment, whose wire form is `...T00:00:00.000Z` — `implementation/clock.py:21-28` (`iso()`), `implementation/serialize.py:6-15` (`_common`/`_dt`).

**Pre-edit search log (the one edit)**

- (a) Subject: rendering of ISO 8601 timestamps in response bodies — the whole class of datetime-valued output fields, not just `attachment_at`/`transit_termination_at` from the Step 7 site.
- (b) Paths enumerated: grepped the entire implementation for `iso(|isoformat|strftime|\.000Z` — the only formatting sites are `clock.iso` (single formatter, hard-codes `%03d` fractional digits), `serialize._common` (`created_at`, `updated_at`), `serialize._dt` (used by *every* datetime field of every projection), `serialize.damage_document` (`received_at` + `created_at`, no `updated_at`/`version`), and `response._meta` (`api_request_timestamp`, also via `clock.iso`). Read `serialize.py` in full and confirmed all 20 business-instant fields route through `_dt`/`iso`: `inception_at`, `expiry_at`, `war_terminated_at`, `sailing_date`, `discharge_date`, `attachment_at`, `transit_termination_at`, `issued_at`, accumulation `window_start_at`/`window_end_at`, survey-order `window_start_at`/`window_end_at`, `period_start`/`period_end`, `loss_date`, `subrogation_notice_at`, `time_bar_at`, `received_at`, `voyage_sailing_date`, `declaration_date`. Also read `routes_registry.py:355-362` (the clock endpoint returns an empty `data`, so it emits no instant) and `validation.py:192-214` (`parse_dt`) to confirm the input side is separate.
- (c) Wording adjustments made to keep all enumerated paths consistent: (1) scoped the sentence to what a **response body** carries, because `parse_dt` on the input side accepts bare-`Z`, fractional-digit and even date-only strings — a symmetric claim would have been a new mismatch; (2) phrased the field list as "such as ..." rather than an exhaustive enumeration, so fields Step 7 never exercised (e.g. `voyage_sailing_date`, `declaration_date`, survey-order window bounds) are covered without the list becoming a closed set; (3) added "A field that is unset is `null` rather than a string" to match `_dt`'s `None` passthrough, which the three-digit claim alone would have contradicted for the many nullable instants (`attachment_at`, `issued_at`, `time_bar_at`, `war_terminated_at`, ...); (4) framed the last clause as prose-vs-wire rather than editing the ~15 individual `...T00:00:00Z` examples in §2.6, §3.3, §3.4, §3.8, which keeps every worked example verbatim and avoids touching the midnight-normalisation and window-boundary rules those examples carry.

The role-header family needed no edit: `implementation/routes_certificates.py:98` authenticates `POST /certificates` as `("Assured",)`, exactly as §4's table and §3.3 ("Declaration is the assured's act, not the underwriter's") already determine. That was a pure fixture bug.

## Step 9: Complete PRD — 2026-09-03T20:45:00.000Z

Run as three sequential file-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 registry+certificate routes, pass 2 claims+GA+premium routes, pass 3 shared infrastructure + all deferred items), rather than one monolithic scan. Rationale: a single agent scanning 2979 lines of implementation against a 460-line PRD reliably degenerates into a shallow skim, and the failure mode is silent — `PRD_COMPLETED.md` comes back byte-identical to its source. Partitioning makes each pass's scope small enough to walk exhaustively and makes the cumulative diff auditable.

Orchestrator verification: PRD.md 458 lines / PRD_FINALIZED.md 460 / PRD_COMPLETED.md 466 lines, 119,060 chars (+19,572 over PRD_FINALIZED — NOT byte-identical, so the scan genuinely ran; `diff` reports 102 changed lines). Heading count unchanged at 28 in both. Tail still ends at the final row of the §5 error table. All 14 implementation source files have mtimes between 18:57 and 19:16, i.e. all predate the 20:02 all-green 8-round sweep, confirming Steps 8 and 9 edited only PRD documents and the recorded pass is valid for the shipped code. Removed a stray `__pycache__` from `workspace/implementation/`.

Cumulative edit total across the three passes: 56 edits — 45 ambiguity-pins, 11 mismatch-revisions.

### Pass 1 summary (routes_registry.py, routes_certificates.py) — verbatim

Pass 1 complete. `PRD_COMPLETED.md` created from `PRD_FINALIZED.md` and edited in place with 15 surgical in-paragraph revisions.

**File integrity**: 460 lines → 460 lines (no structural change; every edit is an in-line revision of an existing line). Chars 99,488 → 104,960 (+5,472). Tail still ends at `| ERR_RECOVERY_EXCEEDS_SETTLEMENT | 422 |`. Diff touches exactly 15 lines, all `NcN` in-place.

**Counts**: 13 ambiguity-pins, 2 mismatch-revisions.

**Changes**
- §2.1 — insert — ambiguity — ownership is enforced only on write paths; reads/lists are role-gated only, so an `Assured` may read another cover's policy or certificate — routes_registry.py:83-88, routes_certificates.py:169-207
- §2.3 — insert — ambiguity — `created_at` ties (the logical clock is frozen) are broken by insertion order — store.py:59-61 as exercised by routes_certificates.py:206, routes_registry.py:178
- §2.3 — insert — ambiguity — list filters are exact-equality, conjunctive, and an unmatched identifier yields `total_count` 0 rather than a 404 — routes_certificates.py:195-205, 421-433
- §2.10 — revise — ambiguity — `expected_open_policy_version` is a mandatory non-negative integer: missing/non-integral/negative is `ERR_INVALID_REQUEST`, any other non-matching integer (0 included) is 412 — routes_certificates.py:238
- §3.1 — revise — **mismatch** — tower nesting and `expiry_at > inception_at` are *not* checked at write time (only `per_certificate > 0`, other two `>= 0`); both are deferred to activation's `ERR_INVALID_STATE` — routes_registry.py:38-40 vs 96-101
- §3.1 — insert — ambiguity — the transit sweep has no state precondition (runs on `DRAFT`/`EXPIRED`, never 409s), only the `ACTIVE → EXPIRED` leg is conditional, and it returns the policy row — routes_registry.py:132-138, services.py:525
- §3.2 — insert — ambiguity — vessel `flag_code` is length-checked only (2 chars, no alpha/ISO test) — routes_registry.py:195
- §3.2 — insert — ambiguity — port `country_code` likewise length-checked only — routes_registry.py:245
- §3.3 — revise — **mismatch** — the four valuation money fields are optional and bounded only at `>= 0` in the schema; `freight_amount` defaults to null and counts as zero; a `0` invoice/declared value is `ERR_VALUATION_INPUT_MISSING` (422), not `ERR_INVALID_REQUEST` — routes_certificates.py:112-116, 42-48
- §3.5 — insert — ambiguity — endorsement re-screens only packaging, voyage dates, valuation inputs and the share ceiling; no hull check, no policy-period test, no other tower comparison; `valuation_basis`/`freight`/`duty`/endpoints/cover flags are not endorsable — routes_certificates.py:283-332
- §3.5 — insert — ambiguity — endorsement does not advance `certificates_issued_count`; the replacement starts at `version` 1 with null declaration id, zeroed reinstatement/return/GA amounts and a war axis re-derived (not inherited); vessel and both ports are touched twice so each `version` advances by 2; the 201 body is the replacement — routes_certificates.py:304-358
- §3.5 — insert — ambiguity — `cancellation_reason` is stored only when supplied and never echoed in the certificate body; cancellation has no policy-status precondition — routes_certificates.py:363-379
- §3.6 — insert — ambiguity — re-tiering to the tier the port already holds is accepted and still bumps `version`; the cascade trigger reads the incoming tier alone, so re-listing an already-`LISTED_AREA` port re-runs it — routes_registry.py:283-293
- §3.6 — insert — ambiguity — reinstatement precondition order and codes: war axis then contractual status both give `ERR_INVALID_STATE` (never `ERR_POLICY_NOT_ACTIVE`/`ERR_ALREADY_TERMINAL`); a negative rate is 400, a rate of exactly 0 is `ERR_INVALID_STATE` — routes_registry.py:111-122
- §3.5 — insert — ambiguity — pre-attachment delivery is `ERR_INVALID_STATE`; `delivered_at` needs no midnight and no attachment floor, a later instant leaves the window pinned, and it is not echoed; ending transit moves no policy ledger and confirm-delivery leaves the policy row wholly untouched — routes_certificates.py:390-408

**Deliberately left to later passes**
- `services.listed_area_cascade` / `reinstate_cascade` internals (links 2–5, per-certificate return arithmetic, declaration recompute) — services.py:447-503.
- All arithmetic helpers invoked from my routes but resident in services.py: `insured_value_for`, `transit_termination_for`, `premium_components`, `run_capacity_tower`, `book_exposure`/`release_exposure`, `cancellation_return`, `classification_decision`.
- validation.py date leniency: `parse_dt` accepts a bare `YYYY-MM-DD`, a naive datetime (assumed UTC) and an offset-bearing datetime (converted to UTC) — this makes e.g. `sailing_date: "2026-09-05"` valid and an offset form fail later as `ERR_VOYAGE_DATES_INVALID`. PRD §2.5 only says "must parse as ISO 8601 UTC".
- Input money is not quantised to 2 dp on storage/echo (`invoice_value: 1000.005` round-trips unrounded) — validation.get_decimal / serialize.num.
- Envelope/`meta` generation (response.py) and unknown-path/405 handling (app.py).
- `certificate_number`, `assured_name`, `code`, `panel_code` have no length bounds in impl (PRD silent) — judged too low-value to pin, flagging in case a later pass disagrees.

### Pass 2 summary (routes_claims.py, routes_ga.py, routes_premium.py) — verbatim

Pass 2 complete.

## File state
- **Before:** 460 lines, 104,960 chars
- **After:** 460 lines, 110,446 chars (+5,486)
- Structure verified: heading list byte-identical to PRD_FINALIZED.md; file still ends at `| ERR_RECOVERY_EXCEEDS_SETTLEMENT | 422 |`. Pass 1's edits untouched.

## Counts
- **20 changes total** — 15 ambiguity-pins, 5 mismatch-revisions.

## Changes
- §3.8 — revise — mismatch — `WAR`/`STRIKES` peril is *not* cross-checked against the certificate's war axis; it is recorded as declared — routes_claims.py:35 (no such check anywhere in `create_claim_file`)
- §3.8 — revise — mismatch — `loss_date` is *not* tested against the certificate's cover interval (attachment .. transit termination) — routes_claims.py:38
- §3.8 — revise — mismatch — `ga_event_id` is resolved whenever supplied (404) but stored only when `loss_type` is `GENERAL_AVERAGE`, else dropped to null; no pre-existing security call and no event-status test — routes_claims.py:39,48-55
- §3.8 — insert — ambiguity — claim-creation nulls pinned (`carrier_name`, `adjusted_amount`, `deductible_applied_amount`, `settled_amount`, `adjusted_by_user_id`, `settled_by_user_id`, `subrogation_notice_at`, `time_bar_at`) — routes_claims.py:69-82
- §3.8 — insert — ambiguity — document append has no claim-state precondition; permitted on terminal `SETTLED`/`DENIED` claims — routes_claims.py:116-129
- §3.8 — insert — ambiguity — all three attendance-window rules are `ERR_INVALID_REQUEST` (400) and run *before* `claim_file_id`/`surveyor_id` resolution; `window_minutes` floors the part-minute — routes_claims.py:266-279, services.py:372-373
- §3.8 — insert — ambiguity — filing before `window_start_at` is `ERR_INVALID_STATE`; `packaging_compliant` mandatory; `damage_percentage_found` bounded 0..100 (0 admissible) — routes_claims.py:340-352
- §3.8 — revise — mismatch — the `SURVEY_ORDERED → SURVEY_RECEIVED` leg is conditional on the claim currently being `SURVEY_ORDERED`; a second report leaves `status` put while still appending the doc and bumping `version` — routes_claims.py:368-370
- §3.8 — insert — ambiguity — the auto `SURVEY_REPORT` doc carries `report_reference` as `reference` and the clock instant as `received_at` — routes_claims.py:361
- §3.8 — revise — mismatch — settlement's GA wait keys on the stored `ga_event_id`, not on `loss_type`; an unlinked `GENERAL_AVERAGE` claim settles freely — routes_claims.py:206-209
- §3.8 — insert — ambiguity — adjust-time measurement inputs overwrite stored values, omitted ones leave them, and all persist through the `DENIED`/`DOCS_INCOMPLETE` branches — routes_claims.py:159-164
- §3.8 — insert — ambiguity — missing basis inputs raise `ERR_INVALID_REQUEST` (400) late, after warranty/survey/docs branches; `sound_market_value` must be > 0 — services.py:322-342 (reached only from routes_claims.py:188)
- §3.8 — insert — ambiguity — the 0.00 floor is depreciation-only; salvage basis stores a negative `adjusted_amount` when proceeds exceed sound market value — services.py:343-345
- §3.8 — insert — ambiguity — survey order created with `packaging_compliant`, `damage_percentage_found`, `report_reference` null — routes_claims.py:298-301
- §3.9 — revise — ambiguity — GA event initial fields split precisely (four arithmetic fields null, two counters 0); no coherence test on `voyage_sailing_date`/`declaration_date`; declaration has no hull precondition — `PENDING_REVIEW`/`BLOCKED`/`GA_HOLD` vessels keep status while counter and `version` still move — routes_ga.py:28-57
- §3.9 — insert — ambiguity — new posting carries `guarantee_amount`/`cash_deposit_amount` null — routes_ga.py:435-436 (services), created from routes_ga.py:90
- §3.9 — insert — ambiguity — the security-call response body is the updated event row, not the postings list — routes_ga.py:95
- §3.9 — insert — ambiguity — the holding policy is touched on every accepted posting, `version` advancing even on a 0.00 deposit — routes_ga.py:180-182
- §3.9 — insert — ambiguity — a posting released with a 0.00 deposit leaves the policy row wholly untouched, `version` included (asymmetric with posting) — routes_ga.py:109-115
- §3.7 — revise — ambiguity — period end <= start is `ERR_INVALID_REQUEST` tested after ownership; opening a declaration has no policy-status precondition; overlap spans declarations in every status; initial null/zero split pinned exactly — routes_premium.py:28-56
- §3.7 — insert — ambiguity — submission against a policy outside `ACTIVE`/`SUSPENDED` is `ERR_INVALID_STATE`, not `ERR_POLICY_NOT_ACTIVE` — routes_premium.py:94-95
- §3.7 — insert — ambiguity — the sweep ignores certificate `status` (superseded/cancelled/transit-ended swept in with their return premium); `DRAFT` excluded only via null `issued_at` — routes_premium.py:98-103
- §3.7 — insert — ambiguity — `audit_note` is stored when supplied, never blanked when omitted, and never echoed in the declaration body; same-auditor test runs after the `UNDER_AUDIT` state check — routes_premium.py:138-146, serialize.py:175-193

(23 bullets covering the 20 edit operations — three edits bundled two related pins each.)

## Left to pass 3
- `parse_dt` leniency (bare `YYYY-MM-DD`, naive-as-UTC, offset→UTC) reaching `loss_date`, `received_at`, window bounds, `voyage_sailing_date`, `declaration_date`, `period_start`/`period_end` — validation.py:192-206.
- Input money not quantised to 2 dp on storage or echo: `claimed_amount`, `damage_percentage`, `sound_market_value`, `damaged_sale_proceeds`, `sacrifice_amount`, `salvage_award_amount`, `guarantee_amount`, `cash_deposit_amount`, `declared_premium_total` are all stored at client precision — validation.py:144-160.
- `num()` rendering Decimals as JSON floats — validation.py:48-52.
- Generic `require_state` terminal/non-terminal split, `ordered`/`ordered_by` tie-breaking by `_seq`, `paginate` slicing and `has_more`, envelope/`meta` generation — errors.py:90-96, store.py:59-65, validation.py:280-283, response.py.
- `find()` treating a non-string body reference as a 404 rather than a 400 — services.py:38-44.
- `services.reconcile_declaration` / `recompute_declaration_totals` arithmetic and the zero-base 100.00 rule (PRD §3.7 already pins the formula; the duplicated helper pair is shared-infrastructure) — services.py:275-315.

### Pass 3 summary (shared infrastructure + all deferred items) — verbatim

Pass 3 complete. All structural invariants hold: headings byte-identical (28), file still ends at the final `ERR_RECOVERY_EXCEEDS_SETTLEMENT` row, error table 45 rows and endpoint table 56 rows unchanged.

## Cumulative (all three passes)
- `PRD_FINALIZED.md`: 460 lines / 99,488 chars
- `PRD_COMPLETED.md`: 466 lines / 119,060 chars
- Delta: **+6 lines, +19,572 chars** (+6 lines = three new paragraphs with their blank lines; two in §2.5, one in §5)

## My pass: 21 edits — 17 ambiguity-pins, 4 mismatch-revisions

- §2.1 — insert — ambiguity — an auth header present but empty is treated identically to absent — validation.py:62
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alnum characters — response.py:12-13
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the **logical clock**, not wall time, so it is constant until the clock moves — response.py:19
- §2.3 — insert — ambiguity — `limit`/`offset` must parse as whole integers; an empty-string value takes the default — validation.py:238-253
- §2.3 — **revise — mismatch** — evidence log is sorted on the *stored* `received_at` (ties by insertion order) and therefore need **not** coincide with creation order — store.py:64-65, routes_claims.py:142
- §2.3 — insert — ambiguity — an enum filter outside its declared set is `ERR_INVALID_REQUEST`, not an empty page; any empty-string filter narrows nothing — validation.py:257-277
- §2.4 — insert — ambiguity — the third fractional digit is reached by **truncation**, not rounding (`...00.999999Z` → `...00.999Z`) — clock.py:26-28
- §2.5 — insert — ambiguity — reference fields are type-checked as strings before resolution (wrong type → 400); `""` resolves to that reference's 404 — validation.py:99-100
- §2.5 — insert (new para) — ambiguity — permissive body handling: media type unenforced, absent/unparseable body read as `{}`, non-object body → 400; explicit `null` counts as absence and falls to defaults; numeric-string and whole-float coercion; empty strings clear un-bounded string fields — validation.py:72-129, 163-189
- §2.5 — insert (new para) — ambiguity — `parse_dt` leniency: bare `YYYY-MM-DD`, trailing `Z`, other offsets converted to UTC, naive assumed UTC — enumerated across all 13 client-suppliable instants — validation.py:192-206
- §2.5 — **revise — mismatch** — "must parse as ISO 8601 UTC" → "ISO 8601" (non-UTC offsets are accepted) — validation.py:196-206
- §2.6 — insert — ambiguity — `current_utc` mandatory but otherwise unconstrained (backwards, non-midnight allowed); the call answers 200 with an empty `data` object — routes_registry.py:356-362
- §2.7 — **insert — mismatch** — money is emitted as a JSON **number**, so trailing zeros are not preserved (`6444.90` → `6444.9`, a zero ledger → `0.0`) — validation.py:48-52
- §2.7 — insert — ambiguity — **no** input money field is quantised; 16 named fields are stored and echoed exactly as supplied, only computed amounts are quantised — validation.py:144-160
- §3.2 — revise — ambiguity — `imo_number` tests length **and** digits, but no IMO checksum — routes_registry.py:189-191
- §3.3 — insert — ambiguity — the policy's `deductible_amount` is rounded half up to 2 dp *as it is copied* onto the certificate (the one quantised input) — routes_certificates.py:156
- §3.4 — insert — ambiguity — the composed effective **war** rate is not persisted; `effective_rate_per_mille` is the only rate the certificate carries — services.py:91
- §3.6 — insert — ambiguity — link-5 recompute internals: §3.7 arithmetic re-run over current membership, after all link-3 returns, once per declaration, moving nothing but the three totals plus `updated_at`/`version` — services.py:296-315
- §3.7 — insert — ambiguity — a **negative** computed total is not special-cased: `abs(variance)` over the *signed* base, so `variance_pct` can be negative and drives `ACCEPTED`; a null `declared_premium_total` counts as zero — services.py:286-289
- §3.9 — revise — ambiguity — residual waterfall's third tie-break is insertion order — services.py:408
- §5 — **insert (new para) — mismatch** — transport failures break the status pairing: unknown path → 404 and bad method → 405, both carrying `ERR_INVALID_REQUEST`; trailing slash is not a distinct path; refused media type normalised to 400 — app.py:39-50

## One near-miss caught by testing
I initially wrote that `imo_number` was length-checked only (matching the `get_str(..., exact_len=7)` call). Booting the app and probing it showed an `imo.isdigit()` guard on the next line (routes_registry.py:190) — PRD_FINALIZED was already correct, and I reverted to a narrower pin. I likewise reverted a claim that a non-string body reference yields a 404: every body reference passes through `get_str` first, so `services.find`'s non-string guard (services.py:38-40) is **dead code**, and the reachable behavior is 400. I verified all other empirical claims (truncation, `null`-as-absent, `7.0`/`"7"` accepted vs `7.5`/`true` rejected, numeric-string money, unquantised `100.005` echo, offset conversion, bare dates, 404/405/trailing slash, empty clock body, enum-filter 400) against the live server.

## Completeness statement
Every behavior in my scope is now pinned, except these, which I deliberately left unpinned as unobservable or as dead code:
- **No upper length bound** on `certificate_number`, `assured_name`, `code`, `panel_code`, `description`, `name`. I pinned the observable half (an empty string clears the schema) but not the absence of a ceiling — no test can assert "an arbitrarily long name is accepted". Skipping this is the call flagged for me in pass 1, and I concur.
- **Serializer key order** (`JSON_SORT_KEYS=False`, with `created_at`/`updated_at`/`version` appended last) — not observable to any sane JSON comparison.
- `imo_number`'s `isdigit()` accepting non-ASCII Unicode digits; `float()` precision loss above 2^53. Both unreachable at realistic values.
- `quantify_loss`'s "capped at the insured value" is **dead code** given the schema's non-negative `damaged_sale_proceeds` and `damage_percentage <= 100`; I left the existing PRD sentence rather than delete a harmless true statement.
- Per-policy interleaving of cascade links 2–5 inside `listed_area_cascade` — unobservable, since the logical clock does not advance and version deltas are identical under either ordering.
- `app.py`'s generic 500 handler — reachable only on an implementation bug, not a specifiable behavior.

With those exceptions noted, `PRD_COMPLETED.md` has no remaining silence or mismatch versus `implementation/`.

---

## Pipeline complete — 2026-09-03T20:45:00.000Z

Step 9 has written `workspace/PRD_COMPLETED.md`. Final state: 238/238 tests passing in all 8 parallel rounds (`workspace/implementation/results.{1..8}.json`), 0 tests deleted, 0 implementation fixes, PRD 458 → 460 (finalized) → 466 (completed) lines.
