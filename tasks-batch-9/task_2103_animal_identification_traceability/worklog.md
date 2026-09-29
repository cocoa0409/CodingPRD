# Worklog — task_2103_animal_identification_traceability

## Step 1: Create task directory — 2026-08-15T00:00:00.000Z

Created `tasks/task_2103_animal_identification_traceability/` and `tasks/task_2103_animal_identification_traceability/workspace/` via `mkdir -p`. Index and folder name were pre-assigned by the invocation (no ./tasks/ scan performed).

## Step 3: Copy shared files — 2026-08-15T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2103_animal_identification_traceability/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-08-15T00:00:00.000Z

Done. All three artifacts are written, lint-clean, and internally cross-checked.

### Files
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

### Structure (above Expert band)
**Profile:** event_sourcing × compliance_audit; topology `graph`; shape `parallel`; role model `segregation_of_duties`; layers: cascading side effects, dual-variant calculation, OCC, derived-field reconciliation.

- **12 entities:** Producer, Premises, DeviceSupplier, TagLot, Tag, Animal, Sighting (immutable), MovementEvent, TraceRequest (with nested `hits[]`), HoldOrder, ReconciliationRun, IncentiveAward — 26 FKs, all reverse-reachable.
- **13 state-machine blocks / 11 entities:** parallel dimensions on Premises (`registration_status` x `health_status`) and Animal (`lifecycle_status` x `trace_status`); cycles on MovementEvent (REPORTED<->DISPUTED, capped at 3), HoldOrder (ACTIVE<->UNDER_APPEAL, capped at 2), DeviceSupplier (APPROVED<->SUSPENDED->REVOKED), Premises registration (ACTIVE<->SUSPENDED); branching on ReconciliationRun (SUBMITTED->{APPROVED, VARIANCE_FLAGGED}).
- **3 OCC rules** (all `ERR_STALE_VERSION`/412): lot-create on DeviceSupplier.version; run-create and hold-create on Premises.version.
- **10 calculations:** two dual-variant on different domains (`premises_tag_book_balance` AS_ISSUED vs AS_SIGHTED; `trace_scope_projection` STRICT_INTERVAL vs PREMISES_WINDOW), plus all three combinatorial modes — (a) `trace_completeness_score`, (b) `incentive_award_amount` per-line rounding, (c) `tag_lot_issuance_fee` pinned discount-then-surcharge order. Also `supplier_conformance_score`, `movement_reporting_timeliness`, `reconciliation_variance`, `animal_location_projection`, `trace_goal_evaluation`.
- **16 validation priorities**, three conflict pairs across distinct category pairs (state<->referential, safety<->temporal, constraint<->fiscal).
- **56 endpoints** (20 GET / 36 POST, incl. `POST /_clock/set_current_utc` with fixed 2026-08-01T00:00:00Z default), **51 errors**, **6 roles** (3 `entity_backed`, 3 `opaque`).

### Design-file counts
- **§1.8: 24 instances** across all 9 rule_ids (2/3/2/2/3/3/3/3/3) — every formula-derived assert is a literal computed by code (fee 169840 & 107692 w/ surcharge 4142; award 686 vs the 685 sum-then-round trap; scores 85.00/82.00/68.00/67.00; variance 0.50; completeness 82.50; elapsed 48.00; lag 72.00).
- **§1.9: 58 instances** over all 9 guide sections (51 executable + 7 `excluded_because` stubs).

### Verification
`scaffold_lint.py` verdict, verbatim:
```
Coverage
  §1.5 endpoints declared:    56
  §1.1 entities declared:     12
  §1.8 instances scanned:     24
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  768

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Additional self-checks: 82 unique instance names, 0 unbound `${var}` across payloads/paths/asserts, 0 forbidden concurrency vocabulary, 0 fuzzy ranking adjectives, no `id` in any ordering/tie-break, all 51 errors referenced by at least one instance (two unreachable ones were fixed: `ERR_INSUFFICIENT_INCENTIVE_BALANCE` deleted as structurally impossible; `ERR_LOT_EXHAUSTED` disambiguated from `ERR_LOT_NOT_ISSUABLE`). No sibling task directory was read.

## Step 4: Generate PRD — 2026-08-15T00:00:00.000Z

PRD generated at `workspace/PRD.md`.

### Output
**439 lines**, 26 headings, ending cleanly at §5 with no audit footer.

**Sections emitted**
- §1 Introduction — 3 paragraphs (traceback urgency -> chain of custody -> voluntary enrolment + privacy)
- §2 Global Specifications — 11 subsections: 2.1 Participants and RBAC, 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Common Resource Properties and the Programme Clock, 2.5 The Order in Which a Request Is Vetted, 2.6 Version Guards on Parent Records, 2.7 Producer Privacy and Read Scope, 2.8 Derived Counters/Cascades, 2.9 Numeric Precision and Money, 2.10 Nested Path Resolution, 2.11 The Sighting Log as the System of Record
- §3 Business Logic — 9 subsections organised as a chain-of-custody timeline: producers/premises/enrolment -> suppliers -> lot issuance -> animal identification -> movements -> holds -> traceback -> harvest+reconciliation -> incentives
- §4 Endpoint table (4 columns, 56 endpoints)
- §5 Error table (2 columns, 51 errors)

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 117 required, 117 present, 0 missing
- endpoints[].request_body: 51 required, 51 present, 0 missing
- endpoints[].query_params: 29 required, 29 present, 0 missing
- endpoints[].path_params: 2 required, 2 present, 0 missing (incl. animalId)
- nested struct members (hits/line_items/clock): 10 required, 10 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 16 checked, 16 expressed as an explicit ascending-priority list in §2.5, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_supplier_version/expected_premises_version + ERR_STALE_VERSION + HTTP 412), 0 missing
- state_machines[].transitions: 55 checked across 13 dimension blocks, 55 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed in operator-free prose, 0 missing
- validations[] conditions: 51 error ids checked, 51 matchable to a condition in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 56 endpoints checked, side effects + applies_to endpoint enumerations expressed, 0 missing
- entities[].fields[] structured content: 117 checked (defaults, initial values, enum members, computed definitions), 0 missing
- sibling-branch symmetry: 6 groups checked (reconciliation APPROVED/VARIANCE_FLAGGED, dispute from REPORTED/RECEIVED, cancel from SUBMITTED/RUNNING, release from ACTIVE/UNDER_APPEAL, lot RECALLED from ISSUED/ACTIVE, supplier SUSPENDED->APPROVED/REVOKED), 0 asymmetric
- enum/state coverage: 66 enum values + all state names present verbatim in backticks, 0 missing
- roles: 6/6 named, all 6 identity: fields translated into §2.1 prose
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 799
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Notable authoring decisions: the pinned evaluation orders (issuance-fee discount keyed on pre-surcharge subtotal, surcharge on the discounted total; per-line rounding before summation in the incentive award) and the two deliberately different sighting orderings (append-order replay for location projection vs. `observed_at` ordering for trace residencies) are each called out explicitly in prose, since both are silent-divergence traps. No fuzzy/approximating language; no `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` was opened.

## Step 6: Generate implementation — 2026-08-15T16:45:00.000Z

The implementation is complete and verified. Here's the report:

## Delivered

`/home/ubuntu/github/CodingPRD/tasks/task_2103_animal_identification_traceability/workspace/implementation/` — Python + Flask, in-memory store, ~2,900 lines:

- `start.sh` — bash launcher, `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), dependency install guarded by a `.deps_installed` sentinel + `import flask` probe so per-test reboots never re-run pip. Cold boot measured at **0.7 s**.
- `app.py` (entry/error handlers, per-request store lock), `db.py` (store + logical clock, **no seeding** — store boots empty), `errors.py`, `respond.py` (envelope), `shape.py` (band-3 field validation), `authz.py` (RBAC/ownership/privacy), `calc.py`, `derive.py` (counters/cascades), `tracescope.py` (traceback BFS), `serialize.py`, `timeutil.py`, `routes/` (12 blueprints, all 56 endpoints).

## Key fidelity decisions

- **Validation runs as an explicit 16-band pipeline** per PRD §2.5, band ordering encoded per endpoint with in-code band comments. Intra-band order follows §3 narrative prose where it differs from §2.5's catalogue listing (e.g. movements check `ERR_SAME_PREMISES_MOVE` before `ERR_ANIMAL_NOT_AT_PREMISES`, per §3.5).
- **All arithmetic uses `fractions.Fraction`** with an exact round-half-up, so no float can perturb a rounding boundary. Verified against PRD-derived literals: fee 169840 (qty 4000, 12 %), 107692 with surcharge 4142 (qty 2000, probation), award line 343 (rounded per line, not on the sum), scores 100.00/88.00/76.00/70.00/64.00, variance 9.73, completeness 62.50/32.50/100.00.
- **Producer re-derivation is deferred and flushed once per request** (`derive.mark_producer` + `after_request` flush). Without this, a movement report bumped the producer's `version` twice (head-count hop + on-time hop); now every record moves exactly one version per request.
- **Two orderings coexist deliberately**: location projection replays by `sequence_no` (append order); residency intervals sort by `observed_at`, `sequence_no`. Residency intervals are half-open with strictly-positive overlap, so degenerate (zero-length) residencies never contact.
- `created_at`/`updated_at` are stamped from the logical clock, not wall time (PRD §2.4 "never the host's wall clock"); only `api_request_timestamp` uses real time.

## Two spec judgement calls worth flagging

1. **`ERR_LOT_EXHAUSTED` is unreachable under strict band ordering.** `unapplied_count == 0` implies every in-range serial is already taken, so any apply/replace against a DEPLETED lot trips `ERR_AIN_OUT_OF_LOT_RANGE` (band 14) or `ERR_DUPLICATE_AIN` (band 15) first. I kept strict priority per PRD §2.5 ("capacity and quota, evaluated last") rather than hoisting exhaustion. If a test asserts `ERR_LOT_EXHAUSTED` on apply-tag, it will get one of the earlier errors — the fix would be a one-line reorder in `routes/lots.py`/`routes/tags.py`, but it would violate the stated ordering.
2. **No capacity check on `POST /tags/{id}/replace`.** §3.4 says replacement is "subject to the same … capacity rules", but the rule itself is "admitting one more active animal must not push the *birth/destination* premises past capacity", and a replacement admits no animal. Applying it would fail every happy-path replace at a full premises.

## Verification

Five hand-written end-to-end suites (~180 assertions) covering: envelope/auth/RBAC, all 12 ownership operations, the privacy gate for all six roles (incl. silent list omission), pagination bounds, OCC on all three guarded creates, every state machine incl. the cyclic ones (correction ×3, appeal ×2, supplier suspend→reinstate), all four cascades (A/B/C/D), both calculation variant pairs (AS_ISSUED/AS_SIGHTED, STRICT_INTERVAL/PREMISES_WINDOW), direction filters, lookback cutoff, dispute/stale-premises penalties, incentive accrual/pay/clawback, and band-ordering spot checks — **all passing, pyflakes clean**.

## Step 5: Generate unit tests — 2026-08-15T17:05:00.000Z

Generated and verified the complete test infrastructure for `task_2103_animal_identification_traceability`.

## Output

**`test_helpers/`** (9 files, ~2,150 lines) — `types.py` (12 entity TypedDicts + 22 enums; `Sighting` correctly omits `updated_at`/`version` as an append-only observation), `api_client.py` (all 56 endpoint methods), `api_errors.py` (51 error IDs + HTTP map, registered with the framework), `assertions.py` (per-entity assertions, lot-partition and award-line invariants, instant comparison), `factories.py` (payload factories + unique `pin`/`supplier_code` generators + AIN builder), `constants.py`, `test_users.py` (per-instance builders for all three entity-backed roles), `fixtures.py` (672 lines: primitives that always re-read parent `version` before OCC writes, plus Tier 2–5 composites — `setup_environmental_contact_graph`, `setup_harvest_ready_animal`, `setup_supplier_with_defects`, `setup_enrolled_producer_with_head`, `setup_premises_under_active_hold`).

**`test_suite/`** (conftest + 10 domain-named files, ~3,380 lines) — **98 tests**.

## Coverage against the design indices

- **Queue A (§1.8):** all 24 difficulty instances × exactly 2 tests = 48 tests.
- **Queue B (§1.9):** 50 of 51 executable instances × 1 test.
- All 7 `excluded_because:` stubs verified to cross-reference a real difficulty instance; none translated.
- Every docstring carries exactly one `Design:` line; a machine audit confirms all 74 tags resolve to real instances with matching `rule_id`/`section`, and every PRD citation is verbatim (whitespace-normalised substring match against `PRD.md`).

## Verification

Ran under `prd-bench-local-run --isolation per-test-server` against `workspace/implementation/`: **98 passed, 0 failed, 0 errors** in 70s. Every fixture chain is reachable and every literal expected value (fees 169840/107692, surcharge 4142, award 686 vs. the 685 trap, scores 85.00/82.00/68.00/67.00/64.00, completeness 82.50, elapsed 48.00, lag 72.00/72.02/120.00, variance 0.50/1.00/10.00/300.00) matches an independent implementation. pyflakes clean; no `skip`/`skipif`/`xfail`; no scaffold references in generated code.

## Gaps left as gaps (PRD-first filter)

1. **`Corner/validations/lot_premises_mismatch_across_two_producers_rejected` — instance skipped entirely.** Its recipe acts as producer B against a lot owned by producer A. PRD §2.1 puts `POST /tag-lots/{id}/apply-tag` under ownership enforcement and says the comparison "walks through the owning premises to its `producer_id`", so a PRD-only reader derives `ERR_NOT_RESOURCE_OWNER` (band 6), not the asserted `ERR_LOT_PREMISES_MISMATCH` (band 14). Reconfiguring the actor doesn't rescue it either — whether the *body's* `birth_premises_id` is also ownership-checked is genuinely open in PRD prose. `ERR_LOT_PREMISES_MISMATCH` therefore has no test.
2. **`ERR_LOT_EXHAUSTED` probe dropped from `Corner/validations/same_premises_move_and_capacity_and_exhaustion_are_rejected`** (the instance's other two probes are tested). The error is unreachable under PRD's stated band order: reaching a `DEPLETED` lot means every in-range serial is already taken, so an in-range AIN fails band 15 (`ERR_DUPLICATE_AIN`) and an out-of-range one fails band 14 (`ERR_AIN_OUT_OF_LOT_RANGE`) — both strictly before band 16.
3. **`discount_pct_applied` value assertions omitted** where non-zero. PRD says the field "records the selected percentage" while stating the tiers as "12 percent"/"5 percent"; `0.12` vs `12` is not uniquely derivable. `fee_cents`/`surcharge_cents` carry the claim instead. (The `== 0` assertion is kept where the tier is 0, since both readings agree.)
4. **Business-instant echoes compared by value, not rendering** (`assert_same_instant`). PRD pins three-fractional-digit rendering for `created_at`/`api_request_timestamp` but not for `observed_at`/`reported_at`/`retired_at`, so those are asserted as instants. `created_at` is still asserted as an exact string.

One faithful-translation adjustment: `Corner/state_machines/entities_start_in_their_declared_initial_states`' recipe creates a hold using the premises version captured at approval, *after* an intervening tag application bumps it — that would 412 on any correct implementation. The fixture re-reads the premises version before the hold create; the instance's asserted outcome (fresh hold is `PROPOSED`) is unchanged.

## Step 7: Run tests and iterate — 2026-08-16T03:47:18.366Z

**Orchestrator note on this file's continuity.** This run is a RESUME of a pipeline attempt that was terminated mid-flight by an account session limit (not a logic error). On inspection the interrupted run had in fact written its Step 6 entry — it sits above the Step 5 entry in this file rather than below it, so `worklog.md` is out of chronological order but complete through Step 6. No entry was backfilled and no earlier text was rewritten; entries continue to be appended from here. Steps 1–6 artifacts were verified present on disk (SCAFFOLD.yaml + both design indices, workspace/INSTRUCTION.md, workspace/PRD.md at 438 lines, test_helpers/ 9 files, test_suite/ conftest + 10 domain files, workspace/implementation/ 25 .py files + start.sh) and were NOT regenerated.

**Orchestrator-side independent verification** (run before accepting the subagent's report): all 8 `results.${i}.json` parsed directly — every round reports total=98 passed=98 failed=0 errors=0 skipped=0, and the sorted test-name list hashes to a single identical digest across all 8 rounds (98 names, sha256 prefix 76cb51fe8ab5), confirming no round silently collected a different subset.

Subagent summary, verbatim:

The loop terminated on the first iteration — the sweep came back clean across all 8 parallel rounds, so no diagnostic protocol steps were triggered.

## Summary

**Iterations run: 1** (one 8-round parallel sweep; no fix/rerun cycles needed)

**Sweep result — all 8 concurrent rounds identical and green:**

| round | total | passed | failed | errors | skipped | duration |
|---|---|---|---|---|---|---|
| 1–8 | 98 | 98 | 0 | 0 | 0 | 75.8–76.1s |

Test-name sets were verified byte-identical across all 8 rounds (98 unique names), so no round silently collected a different subset. Zero tests failed in *any* round, so the union of failures across the sweep is empty — no flakiness signal surfaced.

**Tests deleted:** none. STEP 0 produced an empty failure union, so STEP 1's PRD coverage / unique-derivability checks were never entered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

### Integrity verification (that the green sweep isn't achieved by forbidden means)

Since a first-try clean sweep can mask a suite that was neutered before I arrived, I checked the cardinal-rule escape hatches directly:

- **No skips/xfails.** `grep -rn "skip\|xfail" test_suite/ test_helpers/` returns only two hits, both the word *"skips"* inside a verbatim PRD §2.3 quote in a docstring (`test_01_producers_premises_and_envelope.py:152,303`). No `pytest.mark.skip`, no `xfail`.
- **No seeded data, no on-disk persistence.** `/home/ubuntu/github/CodingPRD/tasks/task_2103_animal_identification_traceability/workspace/implementation/db.py` holds the entire store as plain dicts on a `Store` object constructed empty at import; the only non-dict state is the logical clock, initialised to the PRD-mandated `2026-08-01T00:00:00Z`. Greps for `sqlite|shelve|pickle|json.dump|open(|/tmp|redis|psycopg|seed` across all implementation modules hit only two source comments asserting the no-seed property. Per-test-server isolation therefore genuinely wipes all state.
- **`start.sh` is restart-safe.** It guards `pip install` behind a `.deps_installed` sentinel plus an `import flask` probe, then `exec python3 app.py` in the foreground — which is why ~98 server reboots per round land at ~76s wall time even under 8× concurrent load.

### Pre-existing coverage gaps (informational — not failures, no action taken)

The task's `worklog.md` self-documents three deliberate PRD-First omissions that remain accurate and require no change:

1. `ERR_LOT_PREMISES_MISMATCH` has no test — PRD §2.1 places `POST /tag-lots/{id}/apply-tag` under ownership enforcement (band 6), which pre-empts the band-14 mismatch check for any cross-producer actor.
2. `ERR_LOT_EXHAUSTED` is unreachable under PRD §2.5's stated band order — a `DEPLETED` lot implies every in-range serial is taken, so band 14 (`ERR_AIN_OUT_OF_LOT_RANGE`) or band 15 (`ERR_DUPLICATE_AIN`) fires first. The implementation correctly keeps strict band ordering rather than hoisting exhaustion.
3. `discount_pct_applied` value assertions are omitted where non-zero — PRD states tiers as "12 percent" but the field as "the selected percentage", leaving `0.12` vs `12` not uniquely derivable. `fee_cents`/`surcharge_cents` carry the claim instead.

No further sweeps were warranted: the exit condition (all 8 rounds `passed == total`) was met.

## Step 8: Finalize PRD — SKIPPED — 2026-08-16T03:47:36.726Z

No subagent spawned. The skill's Step 8 skip condition is met exactly: Step 7 exited on its FIRST 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — i.e. zero iterations beyond the baseline.

Rationale (orchestrator judgement, recorded per the non-interactive autonomy mandate): Step 8 exists to patch PRD at the sites where Step 7's fixes revealed PRD-silence or PRD/implementation mismatch. Its input is `<step_7_diff>`, and here that diff is empty — there is no fix site to trace an edit to. Since Step 8's HARD SCOPE rule forbids any PRD edit that does not trace to a specific `<step_7_diff>` item, a Step 8 run on an empty diff could only produce either a byte-identical copy or out-of-scope edits. Skipping is therefore both the specified behaviour and the correct one.

Consequence for Step 9: `workspace/PRD_FINALIZED.md` does not exist, so Step 9 sources from `workspace/PRD.md` per its documented input fallback. Step 9 is NOT skipped — the full PRD-vs-implementation scan is the only way to close silences that impl resolved at generation time without ever producing a Step 7 failure signal, and a clean first sweep makes that residual class larger, not smaller: 98 green tests only prove the suite's assertions are pinned, not that every impl behavior traces to PRD prose.

## Step 9: Complete PRD — 2026-08-16T04:00:36.771Z

**Orchestrator-side verification** (run before accepting the subagent's report): `workspace/PRD_COMPLETED.md` exists; line count is 438, identical to `PRD.md`, and the `##`/`###` header count is 25 in both files — confirming the "no new sections, no new paragraphs" constraint held and every edit landed in-paragraph. Byte delta +5,909 (the subagent's +5,873 is the character delta; § and — are multibyte).

Subagent summary, verbatim:

Wrote `/home/ubuntu/github/CodingPRD/tasks/task_2103_animal_identification_traceability/workspace/PRD_COMPLETED.md`.

**Source vs completed**: `PRD.md` 438 lines / 87,541 chars → `PRD_COMPLETED.md` 438 lines / 93,414 chars (**+5,873 chars**). No new sections, no new paragraphs, no table changes — every edit is an in-paragraph insert or revision.

**Counts**: 28 changes — **24 ambiguity-pins**, **4 mismatch-revisions**.

- §2.2 Response Structure — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars over A–Z/0–9 — respond.py:15
- §2.2 Response Structure — insert — ambiguity — `api_request_timestamp` comes from the host's real clock, not the logical clock — respond.py:16
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`, empty string = omitted; filters are unvalidated exact-string matches (unknown enum value matches nothing); boolean filters accept `true`/`1`/`yes` case-insensitively — shape.py:286-318
- §2.3 Pagination — insert — ambiguity — null `trace_goal_met` matches neither `true` nor `false` — traces.py:74-76
- §2.3 Pagination — insert — ambiguity — ties in `created_at` ordering settled by server insertion order; sighting history ordered globally, falling back to `created_at` then insertion order — db.py:71-74, animals.py:257
- §2.4 Programme Clock — revise — ambiguity — clock setter answers HTTP 200 with a `data` object whose only field is `current_utc` — clock.py:19
- §2.5 band 3 — revise — **mismatch** — the "no cross-field comparisons" rule has one exception: `serial_end &lt; serial_start` is `ERR_INVALID_REQUEST` in band 3, ahead of existence — lots.py:137-138
- §2.7 Privacy — insert — ambiguity — the "owning producer" is the current premises' operator, falling back to birth premises while in transit — authz.py:59-65
- §2.7 Privacy — insert — ambiguity — only the animal and sighting listings filter rows; all other collections return every matching row — premises.py:147, lots.py:195
- §2.8 Cascades — revise — **mismatch** — a recomputation that changes nothing does not re-stamp; the producer is flushed once per request (single version bump); eight operations stamp unconditionally (5 supplier-facing, 3 premises-facing) — derive.py:87-108,154-182, app.py:26-30
- §2.9 Numeric Precision — insert — ambiguity — rounded decimals render as JSON numbers (`100.0`, not `"100.00"`) — serialize.py:17-21
- §3.2 Suppliers — revise — ambiguity — defect `note` validated but not persisted, no defect-report record, any supplier status accepted, response is the supplier — suppliers.py:73-82
- §3.2 Suppliers — revise — **mismatch** — score also re-derived at lot issuance; auto-`SUSPENDED`/`REVOKED` fire only on defect reports and harvest hop 4 — derive.py:257-276
- §3.3 Issuance — revise — ambiguity — `serial_end &lt; serial_start` yields `ERR_INVALID_REQUEST` before FK resolution — lots.py:137
- §3.3 Issuance — revise — ambiguity — `discount_pct_applied` is a 2-dp fraction of one (`0.12`), not a whole-number percentage — calc.py:57
- §3.3 Issuance — insert — ambiguity — `supplier_id` resolves before `premises_id` — lots.py:140-141
- §3.4 Application — insert — ambiguity — apply-tag ownership is judged against the lot's premises operator — lots.py:232-233
- §3.4 Application — insert — ambiguity — device/animal/sighting minted at the clock instant; the animal is returned at `version` 1 — lots.py:292-296
- §3.4 Replacement — revise — **mismatch** — replacement runs no capacity, registration, health or lot-premises check; ownership is against the animal, not the lot; answers HTTP 201 — tags.py:46,52-68,94
- §3.5 Movements — insert — ambiguity — body FKs resolve animal → origin → destination — movements.py:45-47
- §3.5 Movements — insert — ambiguity — the animal must be `ACTIVE` (`ERR_INVALID_STATE`); destination registration/health not examined at departure — movements.py:51-57
- §3.5 Dispute — revise — ambiguity — `reason` validated but not persisted — movements.py:171
- §3.5 Correction — revise — ambiguity — the origin premises' producer is the corrector — movements.py:198-200
- §3.6 Appeal — revise — ambiguity — `grounds` validated but not persisted — holds.py:130
- §3.7 Traceback — insert — ambiguity — insertion order breaks residual ties in both the frozen `hits` sort and the candidate scan — tracescope.py:111,129-130
- §3.7 Hit response — insert — ambiguity — responding is not gated on the request's status (works on `RUNNING`, `COMPLETED` or `CANCELLED`) — traces.py:108-124
- §3.8 Reconciliation — revise — ambiguity — a `DRAFT` run's count/basis/book/variance/actor fields are all null until submission — recon.py:45-52
- §3.9 Incentives — insert — ambiguity — `tier_factor` and `compliance_multiplier` frozen as 2-dp numbers — awards.py:180-181

Notes: all 51 catalogue error codes have live raise sites and each site's trigger is now described; the 12 ownership sites match §2.1 exactly. Tests were used only as cross-reference (all 98 pass across 8 recorded rounds) — every statement above describes `implementation/`.

---

**Pipeline complete.** Steps 1–9 all accounted for: Steps 1–6 verified on disk from the interrupted attempt and not regenerated; Step 7 green on its first 8-round parallel sweep; Step 8 skipped under its documented skip condition; Step 9 produced `PRD_COMPLETED.md`.
