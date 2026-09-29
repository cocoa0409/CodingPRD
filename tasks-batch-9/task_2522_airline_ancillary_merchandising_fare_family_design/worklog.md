# Worklog — task_2522_airline_ancillary_merchandising_fare_family_design

## Step 1: Create task directory — 2026-09-03T05:12:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2522_airline_ancillary_merchandising_fare_family_design` and its `workspace/` subdirectory. Index 2522 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate Scaffold — 2026-09-03T07:20:00.000Z

All three scaffold artifacts for task 2522 are complete, YAML-valid, and lint-clean.

## Files

| File (absolute) | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2522_airline_ancillary_merchandising_fare_family_design/SCAFFOLD.yaml` | 2794 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2522_airline_ancillary_merchandising_fare_family_design/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2367 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2522_airline_ancillary_merchandising_fare_family_design/SCAFFOLD_CORNER_DESIGN.yaml` | 4615 |

`SCAFFOLD.yaml` contains §1.0–§1.7 only (flat top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, global_constants, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles) — verified to contain neither `scaffold_difficulty_design` nor `scaffold_corner_design`. Each design file has exactly one top-level key.

## SCAFFOLD.yaml counts
12 entities · 58 endpoints · 10 state-machine dimensions (parallel shape) · 7 calculations · 49 validation rules (strict priority 1–49) · 60 errors · 6 roles (`role_model: segregation_of_duties`) · 2 concurrency rules. Profile: `expert_plus`, `pricing_engine` × `quota_allocation`, graph topology, layers = dual_variant_calculation / cascading_side_effects / optimistic_concurrency / derived_field_reconciliation, `consistency_model: immediate`.

## Design-index instance counts
- **§1.8 depth probe:** 24 instances across 9 rule groups.
- **§1.9 breadth probe:** 104 instances (80 live recipes + 24 `excluded_because` stubs) over all nine guide sections: entities 13, state_machines 12, calculations 16, validations 11, endpoints 7, errors 31, rbac 5, cross_cutting_complexity_layers 7, consistency_model 2.

## Verification performed
- `scaffold_lint.py`: 936 calls scanned across §1.8+§1.9 → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`
- All 60 error ids are reachable: 18 live triggers in the errors section, the rest owned by other §1.9 sections or by a named §1.8 instance via a stub (a comment map at the head of the errors section records each owner).
- All 104 §1.9 names unique across the union of both design files; every stub's `difficulty_instance` resolves to a real §1.8 name; stub keys are exactly `{difficulty_instance, rationale}` with no `test_recipe`; every live instance has the full four-key `test_recipe`.
- Every asserted literal was recomputed with `/tmp/c2522.py` (bundle valuations, fingerprints, single-rounding seat prices, offer price/EV chains, the 5-bucket revenue split with remainder placement, settlement totals).

Two defects found and fixed while finishing: a `disclosed_fee_fingerprint "ECO_HIDE|2|"` assertion (revision_no only advances on a review rejection, so it must be `|1|`), and 9 stubs whose `difficulty_instance` had been written as `rule_id / instance_name` instead of the bare instance name.

## Step 3: Copy Shared Files — 2026-09-03T07:21:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2522_airline_ancillary_merchandising_fare_family_design/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T07:39:00.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **516 lines / 15,739 words / 113,665 bytes**, ending at a real boundary (the final `ERR_BUNDLE_DISCOUNT_FLOOR_BREACH | 422` row of the §5 table).

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Retailing Roles and Access Control, 2.2 API Response Structure (byte-verbatim from the doc-generator's section-2.2 template, diff-clean), 2.3 Pagination, 2.4 Common Resource Properties and the Logical Clock, 2.5 Basis Points, Cents and Rounding Discipline, 2.6 Optimistic Concurrency Control, 2.7 Validation Precedence, 2.8 The Fee Fingerprint and Content Parity, 2.9 The Point-of-Sale Fee Disclosure Obligation, 2.10 Cascade Semantics, Derived Fields and Version Propagation, 2.11 The Append-Only Ancillary Revenue Ledger
- §3 Business Logic & Workflows — 3.1 The Merchandising Catalog and Fare Family Design, 3.2 Pricing Review, Publication and the Upsell Ladder, 3.3 Flights, Seat Map Segmentation and the Demand Feed, 3.4 Distribution Channels and Publishing Family Content, 3.5 Selling: Booking, Fee Disclosure and Ticketing, 3.6 Merchandising Sessions: Candidate Selection, Dynamic Pricing and Acceptance, 3.7 Seat Assignment and Release, 3.8 Changes, Cancellation and Irregular Operations, 3.9 Revenue Accounting and Channel Settlement
- §4 API Endpoints (Method, Path, Description, Authorized Role(s))
- §5 Error Codes (Error ID, HTTP Status Code)

**Coverage confirmation**
- **58/58 endpoints** — matching the 58 `path:` keys in the scaffold; roles and 201/200 semantics transcribed per endpoint.
- **49/49 validations** — §2.7 is a numbered 1–49 ladder; a script mapping each scaffold validation's `priority` to ladder item N confirmed the correct `error_id` **and** `http_status` in every item (49/49, zero mismatches).
- **60/60 errors** — ids and statuses byte-matched against the scaffold's `errors:` block.

**Hard Contract results**
1. **Field-Name Coverage — PASS.** All **128** entity field names and all **85** distinct request/query/path identifiers appear verbatim in backticks (zero missing).
2. **Rule Coverage — PASS.** All **44** state-machine transitions, both concurrency rules (OCC on `expected_booking_version` and `expected_fare_family_version`), all **7** calculations, every precondition `ERR_*` id, all **205** ALL-CAPS literals, and every `global_constants` value are stated in prose (values spelled out rather than symbol names).
3. **§3 Path Purity — PASS.** 1,085 code spans in §3, zero paths, zero bare HTTP methods, zero method+path combinations.

Orchestrator truncation check: `tail -12` ends on the final error-table row; `grep '^#'` shows all five top-level sections and all 22 subsections present. Not truncated.

## Step 5: Generate Unit Tests — 2026-09-03T08:35:00.000Z

Suite complete and verified.

## Deliverable

**`test_helpers/`** (Stage 1, 9 files, 2,062 lines): `__init__.py` 112, `api_client.py` 308, `api_errors.py` 164, `assertions.py` 254, `constants.py` 158, `factories.py` 380, `fixtures.py` 372, `test_users.py` 94, `types.py` 220.

**`test_suite/`** (Stage 2, 20 files, 9,581 lines): `conftest.py` 31 plus 19 test modules — queue A: test_01 384/7, test_02 271/5, test_03 368/8, test_04 314/6, test_05 206/4, test_06 396/8, test_07 400/6, test_08 406/8, test_09 336/6; queue B: test_10 688/13, test_11 210/2, test_12 744/10, test_13 721/9, test_14 1010/11, test_15 659/7, test_16 579/9, test_17 431/5, test_18 815/9, test_19 612/5.

**138 tests total** (48 queue A, 90 queue B).

## Coverage tally

- **Queue A (Difficulty): 24 of 24 instances translated, 0 skipped.** All 9 rule_ids covered; every instance carries at least 2 tests (the minimum-per-instance check passed).
- **Queue B (Corner): 80 of 80 non-stub instances translated, 0 skipped.** All 9 sections covered. The 24 `excluded_because:` stubs were not translated — a programmatic check confirms no emitted tag resolves to a stub.
- **No instance was skipped**, so there are no gap reasons to report. Where a recipe assertion was not uniquely derivable from the PRD, the individual assertion was dropped or weakened rather than the instance being abandoned; the notable cases are ISO-8601 fractional-second rendering (only `created_at` and `api_request_timestamp` are pinned to three digits in §2.2/§1), `suppression_reason` `""` vs null on a non-empty session, allocation-row `created_at` ordering, `published_family_version` at publication-create (§3.2 and §3.4 disagree on ordering relative to the version bump), and the non-existent fields `zone_base_cents`, `presented_offer_count`, `Booking.seat_count`.

## Tag verification

An AST pass over all 19 modules confirms: 138 tests, 138 `Design:` lines, **exactly one tag per test and always the last docstring line**; 0 dangling tags (every `<rule_id|section>/<instance.name>` resolves verbatim against the two yamls); 0 stub tags.

## Other checks

`python -m py_compile` clean on all 29 files; every module also **imports successfully** under the runner's PYTHONPATH layout (so `from test_helpers import ...` and all referenced symbols resolve); `pyflakes` clean after removing four unused imports (`pytest` in `fixtures.py`, and one each in test_03/test_04/test_09). `__pycache__` removed. No reference to the scaffold, the design indices, or `excluded_because` survives in the emitted code — the only occurrence of "Difficulty" is inside the required tags. `workspace/implementation/` was never read, nor was any sibling task directory.

One inherited fix worth flagging: `test_helpers/constants.py` had drifted from the PRD enums (`OPEN_SALE`/`CHECKIN` phases, `PARTIALLY_REFUNDABLE`, a `META` channel type, `REVENUE_CLASSES = ("AIR","NON_AIR")`, missing `WAIVER_REVERSAL`/`WITHDRAWN`). It was corrected before any test relied on it; two subagent reports mention the stale values because they read the file pre-fix, but their emitted code uses PRD literals.

## Step 6: Generate Implementation — 2026-09-03T08:35:30.000Z

Implementation complete and verified end to end.

## Files written (`workspace/implementation/`)

| file | lines | contents |
|---|---|---|
| `start.sh` (exec bit set) | 10 | guarded `pip install` + `exec python3 app.py` |
| `requirements.txt` | 1 | `flask==3.0.3` |
| `app.py` | 60 | blueprint registration, `ApiError`/`HTTPException`/catch-all handlers, `0.0.0.0:$PORT` (default 10000), `threaded=True` |
| `store.py` | 92 | in-memory dicts, logical clock, `common_fields`/`touch`/`by_created` |
| `errors.py` | 87 | 60-entry `ERROR_HTTP` catalogue, `ApiError`, `fail()` |
| `envelope.py` | 48 | `meta`/`response_type`/`data` envelope, `req_`+20 alnum id, pagination meta |
| `validate.py` | 222 | auth + RBAC, per-type validators, unknown-field rejection, pagination/query filters |
| `calc.py` | 238 | all 7 calculations, round-half-up helper, every global constant |
| `ser.py` | 221 | 12 serializers (RevenueEntry deliberately without `updated_at`/`version`) |
| `svc.py` | 712 | ledger, valuation, fingerprint/parity cascades, ticketing allocation, seats, offers, waivers, clock sweep, resolvers |
| `routes/catalog.py` | 391 | 16 endpoints |
| `routes/ops.py` | 265 | 13 endpoints |
| `routes/dist.py` | 141 | 7 endpoints |
| `routes/sell.py` | 342 | 13 endpoints |
| `routes/offers.py` | 142 | 5 endpoints |
| `routes/revenue.py` | 66 | 4 endpoints |

3027 lines of Python total.

## Coverage (all checked programmatically against SCAFFOLD.yaml/PRD.md, not by eye)

- **Endpoints: 58/58.** Flask `url_map` normalised to `{id}` is an exact set match with the scaffold's 58 declared `(method, path)` pairs — zero missing, zero extra.
- **Validation ladder: 49/49.** Scaffold priorities are contiguous 1..49 and every priority's `error_id` is raised somewhere in the code.
- **Errors: 60/60.** `ERROR_HTTP` matches the PRD §5 table exactly (same ids, same HTTP statuses), no impl-only ids, and every id is reachable from a `fail()` site.
- **Entity fields:** live `GET` responses for all 12 entities contain every scaffold-declared field; the only extras are the §2.4 common fields (and RevenueEntry correctly exposes just `id` + `created_at`).
- **No seeding:** importing `app` leaves all 12 stores at length 0 and the clock at `2026-08-01T00:00:00Z`; no sqlite/file/JSON persistence anywhere.

## Boot smoke test

Booted via `PORT=<high port> bash start.sh`, then ran two scripted end-to-end scenarios (~90 requests) — both passed with every asserted status code:

- catalog → attribute → submit → approve → channel → publication → flight → seat segment → demand snapshot → booking → disclosure → ack → offer session → accept → seat assign → ticket → ledger read → change-open → IROPS waiver → change-settle → rescind → seat release → cancel → phase advance to DEPARTED → paginated ledger reads → 400/404 negatives.
- fresh-store proof, OCC 412 in both stale directions, fingerprint drift (booking→`STALE`, publication→`OUT_OF_PARITY`/`ATTRIBUTE_REPRICED`, channel→`BREACHED` with `parity_breach_count` 1), ticket blocked 409 while stale then allowed after resync + re-disclosure, `WTP_ELASTIC` price chain verified by hand (`11612` bp → `4645` cents → EV `5394`), `RESIDUAL_INVENTORY` variant verified (`7000` bp), cool-off/`NO_ELIGIBLE_CANDIDATES`, touchpoint-phase 409, clock sweep response shape.

## Judgment calls worth knowing

1. **§2.7 numbering is authoritative** over the §3.x prose enumerations where they conflict — e.g. ticketing and offer acceptance check `ERR_CHANNEL_SCOPE_VIOLATION` (6) before `ERR_BOOKING_STATE_INVALID` (9), and disclosure issuance checks `ERR_UNDISCLOSED_FEE_CATEGORY` (28) before `ERR_CHANNEL_CATEGORY_UNSUPPORTED` (31), even though §3.5/§3.6 list them in a different order. Body/query validation (3) always precedes path 404 resolution (4).
2. **change-settle `CONFIRM`:** `change_count` increments on every CONFIRM while the `CHANGE` SALE entry is posted only when the quote > 0. The PRD sentence's punctuation could be read as gating both on the quote; the scaffold's transition bullets separate them, and that is the reading implemented.
3. **`GET /revenue-entries/{id}` with an unknown id** answers 404 with `ERR_REVENUE_ENTRY_NOT_FOUND`, which is raised directly rather than added to the catalogue — the PRD's 60-error table and §2.7 step-4 mapping declare no not-found id for the ledger, so the count stays at exactly 60.
4. **Operational note:** while smoke-testing the impl agent ran a `pkill -f app.py` that likely also killed sibling agents' per-test servers momentarily. The harness relaunches before every test, so at worst a single in-flight test would have reported "could not be restarted"; a re-run of any sweep that was live around that moment is advisable.

### Orchestrator note on Step 6 judgment call 4
The `pkill -f app.py` happened before any Step 7 sweep for this task existed, so it cannot have polluted our own results. It is recorded here because it may have perturbed sibling pipelines on this host.

## Step 7: Run Tests and Iterate — 2026-09-03T08:52:00.000Z

Clean sweep: 138/138 passing in all 8 parallel rounds, zero skips.

## Summary

**Iterations run:** 3 (each an 8-round parallel sweep under `setsid`; 138 tests × 8 rounds, `per-test-server` isolation). Failures were fully deterministic — 15 tests failed in 8/8 rounds in iteration 1, 1 in 8/8 in iteration 2 — so no flakiness was ever in play.

**Tests deleted:** none. All 138 tests survive.

**Fixes applied to `test_helpers/`**

- `test_helpers/factories.py` — the eight named payload wrappers (`checked_bag_product_payload`, `standard_seat_product_payload`, `extra_legroom_seat_product_payload`, `priority_boarding_product_payload`, `wifi_product_payload`, `change_flex_product_payload`, `eco_lite_family_payload`, `direct_web_channel_payload`) hard-pinned their defaults as explicit keyword arguments and then splatted `**overrides`, so any test overriding a pinned field raised `TypeError: got multiple values for keyword argument`. Rebuilt each to merge defaults with overrides in a dict so the caller wins. This was the root cause of 10 of the 15 failures.
- `test_helpers/assertions.py` — added `as_instant` / `assert_instant` / `assert_instants` (exported via `test_helpers/__init__.py`) to compare clock-derived timestamp fields as instants. PRD pins the *instant* ("a `valid_from` equal to the logical clock, and a `valid_until` exactly one hour later") but states a rendering convention only as "an ISO 8601 UTC instant with three fractional digits", and only for `created_at`/`api_request_timestamp`. Three tests were asserting byte-exact `2026-08-10T09:00:00Z` against the implementation's uniform `...09:00:00.000Z`. Per STEP 1c the covered assertion (the instant) is kept and the un-derivable serialization detail dropped.

**Fixes applied to `test_suite/`**

- `test_12_lifecycle_transitions.py` — local `eco_family_payload` helper had the same kwargs-collision bug; made override-safe (4 tests).
- `test_16_error_lifecycle_conflicts.py` — `test_assigning_a_seat_after_departure_is_refused_as_segment_closed` passed `record_locator="CLOSED1"` (7 chars). PRD §3.5: "a `record_locator` of exactly six characters drawn from uppercase A–Z and the digits". The implementation correctly answered `ERR_INVALID_REQUEST`; the fixture literal was wrong. Changed to `"CLOSED"`. Every `record_locator` literal in the suite was audited — this was the only invalid one.
- `test_02_offer_pricing.py`, `test_06_boundary_precision.py`, `test_08_seat_and_offer_overlap.py` — switched `valid_from`/`valid_until` to `assert_instants`.
- `test_03_family_lifecycle_and_flight_state.py` — `test_rejection_cycle_advances_the_revision_and_the_fingerprint` asserted `review_note` was present on the returned fare family. PRD mentions `review_note` in exactly one sentence (§3.2: "supplying `decision` … and optionally a `review_note`"), purely as an operation input; it never states the note is persisted onto the family or exposed on the resource, and §3.1's explicit enumeration of the family's fields omits it — unlike `reviewer_user_id`, which PRD does explicitly stamp. Per STEP 1c the test was split rather than deleted: the three covered assertions (`status="PUBLISHED"`, `revision_no=2`, `reviewer_user_id`) are kept and the uncovered `review_note` assertion removed.

**Fixes applied to `implementation/`:** none. Every failure traced to the test layer — no implementation defect was found, and no PRD-required check was weakened or removed.

### Orchestrator independent verification of Step 7
Per the known failure mode where a Step 7 agent can report a clean sweep with no artifacts on disk, the orchestrator re-read the artifacts directly rather than trusting the report:
- All 8 `workspace/implementation/results.{1..8}.json` exist (~42.6 KB each, all timestamped 08:45).
- Each parses to `{'total': 138, 'passed': 138, 'failed': 0, 'errors': 0, 'skipped': 0}`.
- `grep` for `pytest.mark.skip` / `pytest.mark.xfail` across `test_suite/` and `test_helpers/`: 0 hits.
- 138 `def test_` functions and 138 `Design:` tag lines — the suite was not shrunk to reach green.
Step 7's report is corroborated.

### Step 8 gating decision
Step 7 reported 0 `implementation/` fixes but non-zero `test_suite/` and `test_helpers/` fixes, so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 impl fixes) is NOT met. Step 8 runs. Its focus list is narrow by construction: the only Step 7 items that reveal PRD silence rather than pure fixture bugs are (a) the timestamp-rendering convention behind `assert_instants`, and (b) the `review_note` non-persistence. The factory kwargs-collision and the 7-character `record_locator` are pure test bugs and must NOT produce PRD edits.

## Step 8: Finalize PRD — 2026-09-03T09:00:00.000Z

Done. Two edits, both traced to the two Step 7 items that were genuine PRD silences; the two fixture-bug items produced no PRD edit.

## Line counts
- `PRD.md`: 516 lines → `PRD_FINALIZED.md`: 518 lines (+2 lines, **+0.39%**). Two paragraphs touched (one inserted, one revised in place); no sections added.

## Changes

- **§2.4 (Common Resource Properties and the Logical Clock)** — *insert* — new paragraph "**Rendering server-minted timestamps.**" pinning that every server-minted timestamp renders as an ISO 8601 UTC instant with exactly three fractional digits and a trailing `Z` (`created_at`, `updated_at`, `valid_from`, `valid_until`, `declared_at`, `disclosure_issued_at`, `disclosure_acked_at`, `last_resync_at`, `current_utc`, `api_request_timestamp`), null stays null, with `accounting_period` and client-supplied `scheduled_departure_utc` explicitly carved out — `implementation/store.py:56-61` (`iso()`), consumed at `implementation/ser.py:10-11`.
- **§3.2 (Pricing Review…)** — *revise* — the `review_note` sentence now states the note is a free-text string that may be omitted or sent as explicit null, is stored nowhere, is persisted by neither decision branch, and never appears in any response — `implementation/routes/catalog.py:206` (accepted via `v.nullable(v_str)`, never written), `implementation/ser.py:29-50` (family serializer omits it).

## No-edit items (from `<step_7_diff>`)
- `test_helpers/factories.py` kwargs-collision — pure test-layer bug; PRD says nothing about factory shape.
- `test_16` `record_locator="CLOSED1"` — the implementation's `RE_LOCATOR = ^[A-Z0-9]{6}$` (`implementation/validate.py:21`) already matches PRD §3.5 verbatim; fixture literal was wrong.

## Per-edit pre-edit search log

**Edit 1 — timestamp rendering**
- (a) Subject: how the server renders every timestamp-valued field in any response body.
- (b) Paths enumerated and read/grepped: `store.py:56-61` `iso()` (str passthrough branch, `microsecond // 1000` truncation, `None` → `None`); every serializer in `ser.py` — `_common` (line 10, all 11 versioned entities), `publication.last_resync_at` (128), `booking.disclosure_issued_at`/`disclosure_acked_at` (146-147), `offer.valid_from`/`valid_until` (186-187), `waiver.declared_at` (200), `revenue_entry.created_at` (211) and its raw `accounting_period` (219), `flight.scheduled_departure_utc` (74, **not** passed through `iso`); `envelope.py:16-18` `_meta()` → `api_request_timestamp`; `routes/revenue.py:25` `current_utc`; `routes/ops.py:29,38` + `validate.py:83-87` `v_datetime` (returns the caller's string unmodified, so `scheduled_departure_utc` round-trips byte-identically); `store.py:64-66` `accounting_period()` (`%04d-%02d`); grepped every write site of the clock-derived fields (`routes/dist.py:90,138`, `routes/sell.py:52-53,125-126,148`, `routes/ops.py:211`, `svc.py:543-544`) to confirm all hold `datetime` objects, never pre-formatted strings, so the `isinstance(dt, str)` passthrough is dead for them; grepped `env.obj({`/`env.created({` across all routes — `routes/revenue.py:25` is the only ad-hoc (non-serializer) payload in the service, and `svc.py:564` confirmed the offer-session payload carries no timestamp.
- (c) Adjustment: the first draft said "every timestamp field", which would have been a false universal — `scheduled_departure_utc` is echoed verbatim, and `accounting_period` sits inside the very §2.4 list the new sentence attaches to. Narrowed to "every timestamp field the server itself mints", replaced the phrase "the clock-derived fields just listed" with an explicit field enumeration, and added the two explicit carve-outs. Sub-millisecond behaviour (truncate vs. round) was deliberately left unstated rather than guessing at a rule Step 7 never exercised.

**Edit 2 — `review_note` non-persistence**
- (a) Subject: the lifecycle of the `review_note` input to the fare-family review-decision operation.
- (b) Paths enumerated and read/grepped: repo-wide `grep -rn "review_note" implementation/` returned exactly one hit, `routes/catalog.py:206`; read the whole handler `routes/catalog.py:201-235` and confirmed neither the `REJECT` branch (214-221) nor the `APPROVE` branch (222-235) reads `data['review_note']`; `validate.py:152-182` (`fields`/`nullable`) to confirm both absence and explicit JSON `null` are accepted while a non-string is `ERR_INVALID_REQUEST`; `ser.py:29-50` `family()` to confirm the field is absent from the resource; family creation and the PATCH reposition in `routes/catalog.py` to confirm no other path could introduce it.
- (c) Adjustment: dropped a drafted clause asserting the family's fields "are exactly those enumerated in §3.1" — an unnecessary universal about the whole serializer. Also checked the sibling free-text inputs (`reason` on status-change, `cancel_reason`, `release_reason`, `rescind_reason`) before choosing wording: `rescind_reason` and `released_reason` *are* persisted (`ser.py:204`, `ser.py:170`), so every sentence was scoped strictly to `review_note` rather than making any general statement about free-text operation inputs.

### Orchestrator verification of Step 8
`diff PRD.md PRD_FINALIZED.md` shows exactly two hunks — the §2.4 insertion at line 104 and the §3.2 in-place revision at line 246 — matching the report with nothing extra. 518 lines; tail still ends on the final error-table row, so no truncation.

## Step 9: Complete PRD — 2026-09-03T09:35:00.000Z

Run as THREE sequential file-partitioned passes over the same `PRD_COMPLETED.md`, per the known failure mode where a single-pass Step 9 returns a byte-identical copy. Each pass owned a disjoint slice of `implementation/`; passes 2 and 3 were explicitly forbidden from re-copying the file.

### Pass 1 — cross-cutting layer (`app.py`, `envelope.py`, `store.py`, `errors.py`, `validate.py`, `ser.py`)
`cp PRD_FINALIZED.md PRD_COMPLETED.md`, then 8 ambiguity-pins + 3 mismatch-revisions (+3,772 chars, 11 hunks). Behaviour verified empirically by booting the app on a scratch port and probing ~40 edge requests.
- §2.1 — revise — mismatch — "absent or empty" → "absent, empty, or made up entirely of whitespace" (headers are stripped before the emptiness test) — `validate.py:29`
- §2.2 — revise — ambiguity — `api_request_id` pinned as `req_` + exactly 20 chars from uppercase A–Z and digits — `envelope.py:9,12-13`
- §2.3 — insert — ambiguity — list ordering tie-break pinned: rows sharing a `created_at` (routine under the frozen logical clock) come back in server-creation order, and every list including nested ones uses that same total order — `store.py:90-92`
- §2.4 — insert — ambiguity — client-supplied instants accepted with trailing `Z`, an explicit numeric offset, or no zone at all (read as UTC); only `to_iso8601` is normalised to UTC — `validate.py:83-87,118-130`
- §2.6 — insert — ambiguity — both `expected_*_version` fields are integer-only with no range, so 0/negative are well-formed and fail the equality check (412, not 400) — `dist.py:337`, `offers.py:431`
- §2.7 step 3 — insert — ambiguity — six uniform shape rules: integer fields reject bools/numeric strings/`5.0`; id fields must be non-empty strings (blank id = 400, not 404); `row` and `expected_*_version` carry no range; **explicit JSON null is never accepted for any field**; enum arrays must be duplicate-free while `requested_product_ids` may be empty/repetitive; free-text fields accept `""`; absent/empty/`null` body = empty object with no `Content-Type` requirement, non-object body = 400; unknown query params ignored, id filters opaque (empty page, not 404), enum filters rejected — `validate.py:49-115,136-173,188-222`
- §2.7 step 4 — insert — ambiguity — unresolvable revenue-entry id answers 404 with `ERR_REVENUE_ENTRY_NOT_FOUND`, an id the §5 table does not list — `routes/revenue.py:516-522`
- §3.2 (review decision) — revise — mismatch — Step 8's `review_note` non-persistence edit kept, but its "or supplied as an explicit null" clause corrected: null is a shape failure — `validate.py:167-171`
- §3.2 (upsell ladder) — revise — mismatch — a reposition cannot clear the parent with an explicit null (400); it can only re-point at another family — `catalog.py:269`
- §4 preamble — insert — ambiguity — a merchandising session answers 201 whether or not it presents offers; the clock-set call answers 200 — `offers.py:397`, `revenue.py:509`
- §5 preamble — insert — ambiguity — four identifiers outside the 60-code table, same envelope: `ERR_REVENUE_ENTRY_NOT_FOUND` (404), `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) — `app.py:32-48`

Found already uniquely pinned (no change): the 60-error catalogue and every HTTP status; all 12 serializers' field sets/types/null rendering (RevenueEntry alone omits `updated_at`/`version`; internal `_seq` never serialized); envelope shape, `response_type` values, pagination `limit`/`offset`/`total_count`-before-window/`has_more`; UUID-without-prefix ids; `version` starting at 1 and incrementing by exactly 1; default clock `2026-08-01T00:00:00Z` with no wall-clock fallback; auth→role→shape→path-404→body-ref-404→scope precedence.

Pass 1 flag: two of its three mismatch-revisions touch nullability, one inside Step 8's §3.2 edit. It preserved that edit's substance (non-persistence) and corrected only the "explicit null accepted" clause, because `validate.py:167-171` rejects explicit null before `nullable()` is consulted — no field in the API accepts `null` (confirmed live for `upsell_parent_family_id`, `override_price_cents`, `review_note`, `requested_product_ids`). No test exercises an explicit null, so the suite does not contradict impl here.

### Pass 2 — calculation/service layer (`calc.py`, `svc.py`)
7 ambiguity-pins + 2 mismatch-revisions (+3,113 chars, 9 hunks). All Pass 1 hunks confirmed byte-intact.
- §2.8 — insert — ambiguity — re-deriving `content_parity_status` mutates the channel only when the derived value differs; a resync/retirement leaving status unchanged leaves `updated_at`/`version` alone — `svc.py:177-183`
- §2.11 — insert — ambiguity — a mirroring/compensating entry copies the source's `category`, `product_sku`, `tax_treatment`, `revenue_class`, `revenue_account_code` and `source_ref` verbatim, except the two irregular-operations kinds which write `waiver:<waiver id>` — `svc.py:101-108`
- §3.1 (bundle valuation) — revise — mismatch — "excluded from every output" narrowed to family-level outputs: a `WITHDRAWN` attribute keeps `effective_unit_cents`/`attr_value_cents` populated and both are recomputed on every later family rebuild — `svc.py:132-142`
- §3.1 (reprice cascade) — insert — ambiguity — the PUBLISHED-family four-way cascade fires only when the rebuild actually moves `fee_fingerprint`; a fingerprint-neutral reprice still bumps attribute and family `version` but drifts no publication and stales no booking — `svc.py:153-157`
- §3.3 (demand feed) — insert — ambiguity — a demand snapshot mutates every segment of the flight even when the recomputed `effective_price_cents` is identical — `svc.py:262-265`
- §3.6 (ranking) — insert — ambiguity — a fourth ranking tiebreak after `created_at`: server creation order, oldest first (load-bearing because the frozen clock makes a whole catalog share one `created_at`) — `svc.py:537-540`
- §3.8 (cancellation) — insert — ambiguity — `refundable` is read from the catalog product matched by the entry's `product_sku`, so the `CHANGE_SETTLEMENT` change-fee sale is never reversed; and the pass does not skip a seat sale the accompanying release already mirrored, so a refundable confirmed seat is reversed twice — `svc.py:389-393`
- §3.8 (waiver declaration) — insert — ambiguity — every booking the declaration reaches (credited, merely marked, or only seat-released by the diversion cascade even when not `TICKETED`/`CHANGE_PENDING`) is recomputed once and gets exactly one `version` increment for the whole declaration — `svc.py:592-624`
- §3.8 (rescission) — revise — mismatch — scope widened from "every booking this waiver credited" to every booking the declaration reached (`_applied_bookings`) — `svc.py:641-651`

### Pass 3 — route layer (all 6 `routes/*.py`, all 58 handlers)
10 ambiguity-pins + 7 mismatch-revisions (+3,675 chars). All 19 prior hunks confirmed intact; both items Pass 2 handed off were resolved.
- §3.2 (submit) — revise — mismatch — the ownership/`ERR_ROLE_NOT_PERMITTED` check precedes every state check — `routes/catalog.py:203-215`
- §3.2 (review decision) — revise — mismatch — `ERR_SEGREGATION_OF_DUTIES` pinned ahead of `ERR_FAMILY_STATE_INVALID` — `routes/catalog.py:227-236`
- §3.2 (status change) — insert — ambiguity — the mandatory `reason` is stored on no field and echoed by no response — `routes/catalog.py:262`
- §3.2 (reposition) — revise — ambiguity — a reposition supplying no field is well-formed, changes nothing, and still bumps `updated_at`/`version` — `routes/catalog.py:296-317`
- §3.3 (create flight) — insert — ambiguity — `origin` equal to `destination` is refused with `ERR_INVALID_REQUEST` — `routes/ops.py:34-35`
- §3.3 (create segment) — insert — ambiguity — `row_end` below `row_start` is `ERR_INVALID_REQUEST`, decided before the flight/product lookups, outranking either 404 — `routes/ops.py:127`
- §3.4 (create publication) — insert — ambiguity — `published_family_version` is pinned after the family's version bump, so it is one greater than the supplied `expected_fare_family_version` — `routes/dist.py:93-97`
- §3.5 (issue disclosure) — insert — ambiguity — there is no `disclosure_state` guard: issuance is accepted from `PENDING_ACK`/`ACKNOWLEDGED` too, re-snapshotting and discarding an existing acknowledgement — `routes/sell.py:104-127`
- §3.5 (issue disclosure) — revise — mismatch — `ERR_UNDISCLOSED_FEE_CATEGORY` wins over `ERR_CHANNEL_CATEGORY_UNSUPPORTED` — `routes/sell.py:109-118`
- §3.5 (ticketing) — revise — mismatch — `ERR_CHANNEL_SCOPE_VIOLATION` is first of the nine conditions, ahead of the `HELD` check — `routes/sell.py:157-160`
- §3.5 (ticketing effects) — revise — mismatch — "six things in order" corrected to "seven", matching the enumeration (handed-off item 2) — `svc.py:365-374`
- §3.6 (session) — insert — ambiguity — a session mutates no pre-existing row, so the booking's `version` is unchanged and a pre-session read is still valid as `expected_booking_version` — `routes/offers.py:53-55`
- §3.6 (accept offer) — revise — mismatch — "Seven conditions" → eight, reordered to scope → booking-state → offer-state → window → version → parity → `ERR_CHANNEL_CATEGORY_UNSUPPORTED` → price cap — `routes/offers.py:93-110`
- §3.7 (assign seat) — insert — ambiguity — scope and the `HELD`/`TICKETED`/`CHANGE_PENDING` booking-state gate run ahead of the four segment checks, and nothing requires the segment to be on the booking's flight, so cross-flight assignment is accepted — `routes/sell.py:256-273`
- §3.7 (auto-confirm) — revise — mismatch — only the `SALE` entry is conditional on `price_charged_cents > 0`; the money recompute and booking `version` bump are unconditional, and the `HELD` path touches the booking not at all; segment `version` increments on both paths (handed-off item 1) — `routes/sell.py:286-298`
- §3.8 (change settle CONFIRM) — insert — ambiguity — `change_count` and the money recompute happen even when the quoted fee was zero — `routes/sell.py:217-224`
- §3.8 (cancellation) — revise — ambiguity — `cancel_reason` is mandatory input but recorded nowhere and echoed by no response — `routes/sell.py:234`

### Totals and orchestrator verification
25 ambiguity-pins + 12 mismatch-revisions = 37 changes across 31 diff hunks.
- `PRD.md` 516 lines / 113,665 chars → `PRD_FINALIZED.md` 518 / 114,863 → `PRD_COMPLETED.md` 518 / 125,423 (**+10,560 chars over PRD_FINALIZED, +9.19%**; zero line-count change because every edit is in-paragraph, and no new sections).
- `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` — the scan genuinely ran.
- `diff` hunk count 31, matching the three passes' reports (11 + 9 + 17 changes landing on 31 hunks, four Pass-3 edits extending prior-pass text in place).
- §4 still lists exactly 58 endpoint rows; §5 still lists exactly 60 error rows; 28 headings intact; tail still ends at `| ERR_BUNDLE_DISCOUNT_FLOOR_BREACH | 422 |` — no truncation.

Pipeline complete. `workspace/PRD_COMPLETED.md` written.
