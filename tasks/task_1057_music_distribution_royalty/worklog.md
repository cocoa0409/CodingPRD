# Worklog — task_1057_music_distribution_royalty

## Step 1: Create task directory — 2026-07-18T09:02:53.759Z

Created `tasks/task_1057_music_distribution_royalty/` and `workspace/` (pre-assigned folder; no index scan).

## Step 2: Generate scaffold (Expert) — 2026-07-18T09:39:18.259Z

All three scaffold artifacts are generated and lint-clean.

## Files written
- `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8), `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

## Lint verdict (verbatim)
```
Coverage
  §1.5 endpoints declared:    73
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  995

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Clean on the first run — no fix loop needed. All three files pass `yaml.safe_load`.

## Shape (Expert)
- **Profile**: ledger_reconciliation × workflow_orchestration; graph topology (SplitShare and RoyaltyLine are true junctions); cyclic state machines; segregation_of_duties; immediate consistency. Layers: OCC, cascading side effects, dual-variant calculation, rate/threshold triggers.
- **14 entities / 73 endpoints / 29 validations / 29 errors / 12 calculations / 8 state machines / 6 roles / 2 OCC rules.**
- Logical clock `POST /api/_clock/set_current_utc` with the mandated `2026-07-01T00:00:00Z` startup default.

## Difficulty coverage
All nine §0.5 rules × 2 instances (18 total), each with a differentiated pairing:
- **Dual-variant**: statement PROVISIONAL vs FINAL commission (revenue domain) vs treaty-vs-statutory withholding (payee-tax domain).
- **Combinatorial**: mode (b) two-level floor + largest-remainder payout allocation, and mode (a) nested min/max effective commission rate. A mode (c) circular-looking Content-ID bonus is also declared.
- **Non-linear machines**: cyclic Delivery (retry loop) vs parallel `Release.status × Release.delivery_status`.
- **Cascades**: depth-4 takedown chain, depth-3 statement-close payout chain, different triggers.
- **Priority pairs**: state↔fiscal and safety↔referential.
- **Boundaries**: payout threshold 2000/1999 and zero-share split sheet.
- **Cross-entity**: (Release, Subscription) grace window and (Delivery, SplitSheet) lock gate.
- **Temporal overlap**: buffer-expanded aggregate capacity on Store vs pairwise half-open adjacency on Artist.
- **Compensating invariants**: money (`pending + lifetime + reversed`) and non-monetary release-slot count.

## Notes
- Every formula-derived assertion literal was computed in Python against the declared formulas and constants (e.g. commission 75000→90000, bonus 2000, net 425000→412000, payouts 302144/109856, 283/283/284, withholding 201 at exact half-cent).
- All named constants are declared with concrete values in a `domain_constants:` block plus each calculation's `constants:` — no bare named constants.
- §1.9 has 54 instances (40 full recipes + 14 `excluded_because` stubs pointing at named §1.8 instances).
- Two §1.5 additions were forced by the §1.8/§1.9 reachability audit: `POST /api/releases/{id}/go-live` and `status?` on the store/plan create endpoints.

## Step 3: Copy shared files — 2026-07-18T09:39:18.259Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-18T09:47:29.541Z

PRD.md — 433 lines (432 on disk), 73 endpoints documented, 29 error codes. Verified stable (no stall-race) and endpoint count == scaffold's 73.

Hard Contract reports: Field coverage PASS (89/89 entity fields, 52/52 request bodies, 14/14 query params, 5/5 computed report outputs). Rule coverage PASS (30/30 validations with explicit ordered precedence list in §2.8, 2/2 OCC rules → ERR_STALE_VERSION/412, 34/34 state transitions across 8 machines, 12/12 calculations, 7/7 sibling-branch symmetry groups). Path purity PASS (690 backtick tokens scanned in §3, 0 paths/methods leaked).

All 24 domain constants pinned inline with concrete values (7-day lead, 30-day grace, 3 attempts, 10000 bps split total, 60+15-min buffered window, 2000-cent payout threshold, 90-day reversal, 60000-cent 1099 threshold, 50-cent floor / 2000-bps cap, 3000-bps Content-ID rate, loyalty/bonus tiers, four withholding rates + five treaty countries, 2026-07-01T00:00:00Z clock default) — no undeclared scaffold constants, no pre-patching needed. Three transition preconditions carried no scaffold error mapping (approve-without-upc, submit-with-zero-tracks, retry-past-attempt-cap) → documented as ERR_INVALID_STATE per validation priority 7. Neither design YAML was opened.

## Step 5: Generate unit tests — 2026-07-18T10:10:53.810Z

**`test_helpers/`** (1,663 lines, 9 modules) — `types.py` (18 enums + TypedDicts, with `RoyaltyLine` correctly omitting `updated_at`/`version` per its `common_fields: false` status), `api_client.py` (one method per each of the 66 endpoints), `api_errors.py` (all 29 error IDs registered so `validate_error` auto-checks HTTP status), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (per-instance `make_artist_headers`/`make_collaborator_headers` builders for the two `entity_backed` roles), and a 5-tier `fixtures.py` culminating in `setup_world`, `lock_sheets_for_world`, `setup_delivered_release`, `setup_closed_statement`, `setup_single_payee_payout`.

**`test_suite/`** — 90 tests across 9 domain-language files, all collecting cleanly under pytest.

Coverage: Queue A (difficulty) all 18 instances × ≥2 tests each — no shortfall. Queue B (corner) 53 of 54 non-stub instances × ≥1 test; all 14 `excluded_because:` stubs verified to resolve to real difficulty instances and correctly left untranslated. Verified mechanically: exactly one valid `Design:` tag per test, every citation survives a whitespace-normalized grep of PRD.md, no skip/skipif/xfail, no scaffold references.

Three judgement calls:
1. **One instance skipped as a PRD gap** — `Corner/state_machines/accepting_the_same_split_share_twice_is_rejected`. §3.4 declares a precondition for *rejecting* an already-accepted share but none for *accepting* one; a PRD-only implementer could faithfully ship idempotent re-accept. Fails unique derivability.
2. **Design-index arithmetic error on `variant_delta_cents` (sign).** Two instances assert `+13000`/`+200`, but PRD §3.9 defines the field as "the final `net_cents` less `provisional_net_cents`" → `-13000`/`-200`. Asserted the PRD-derived values.
3. **Design-index error on a withholding rate.** `paying_a_payout_whose_payee_tax_form_is_not_verified_rejected` asserts `withholding_bps == 3000` for a `US` payee with `tax_form_status` `SUBMITTED`, but the PRD ladder routes that payee to the US zero rate. Emitted the test asserting the instance's actual claim (the `ERR_TAX_FORM_NOT_VERIFIED` gate + successful retry after verification) and dropped the contradicting money figures.

All other pre-computed literals in both indices independently recomputed and confirmed — 283/283/284 largest-remainder split, 2525-bps effective rate clamped to the 80000 cap, Content-ID bonus tier at exactly 50000 vs 49999, 200.5→201 half-up withholding, buffer-expanded window where 11:30 touches 11:15 without intersecting.

## Step 6: Generate implementation — 2026-07-18T10:10:53.810Z

`start.sh` (guarded dep install, `exec python3 app.py`, binds `0.0.0.0:$PORT`), `app.py` (blueprint registration, error handlers, per-request lock so multi-hop cascades are atomic), `db.py` (in-memory store + logical clock default `2026-07-01T00:00:00Z`), `errors.py` (29 codes), `response.py`, `middleware.py`, `validation.py`, `services/core.py`, `services/calc.py`, and 10 `routes/` modules.

Verification: **73 `/api` routes registered — exactly matching the 73-row PRD endpoint table** (orchestrator independently confirmed 73). Every module passes `py_compile`; no seeding; boots fresh via `start.sh` in ~4s. Three end-to-end smoke runs covering the full release→delivery→statement→payout→1099 pipeline, all 29 error codes' major paths, the takedown 4-hop cascade, auto go-live, OCC on both guarded endpoints, store-window half-open intersection, collaborator bucket conservation.

Two PRD ambiguities resolved literally:
1. **§3.4 accept vs reject version bumps** — accept recomputes `accepted_share_count` without bumping the sheet's `version`; reject bumps sheet + rejecting share only. Follows §3.4's explicit enumeration over §2.4's general rule.
2. **`created_at` source** — stamped from the logical clock per §2.5, with an internal insertion sequence as stable tiebreak for list ordering and the waterfall's `created_at ASC` ties.

## Step 7: Test and iterate — 2026-07-18T10:17:18.128Z

All 8 rounds green at 90/90.

**Iterations run:** 2 sweeps (8 rounds each, 2 waves of 4).
- Sweep 1: 89/90 in all 8 rounds — one deterministic failure, `test_content_id_bonus_tier_is_selected_at_exactly_fifty_thousand_cents` (`TypeError: string indices must be integers, not 'str'`).
- Sweep 2: 90/90 × 8, 0 failures, 0 errors.

**Tests deleted:** none. The single failure was a test-artifact bug, not a PRD-silence case — PRD §3.8 verbatim covers both the 50000-cent tier boundary and the 200/500 bps rates, and the assertion uniquely follows from it.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** `test_08_statement_close.py` line 408 — the tuple destructuring `track_id, store_yt = world["track"]["id"], world["store"]["id"]` bound `store_yt` to the id *string*, but the two `royalty_line_payload(...)` calls below then indexed it as `store_yt["id"]`. Changed the binding to `world["store"]` (the dict, per `fixtures.py:350`) so the existing `store_yt["id"]` uses resolve. Assertions untouched.

**Fixes applied to `implementation/`:** none — the implementation passed all 90 tests unmodified.

Effectively a clean implementation pass: the only defect in the whole sweep was a local variable-binding error inside one test, so Step 7 surfaced zero implementation bugs and zero PRD-silence deletions.

Orchestrator verification: all 8 results.{1..8}.json read directly — 90/90 each.

## Step 8: Finalize PRD — 2026-07-18T10:18:00.000Z

**Outcome: 0-edit PRD_FINALIZED.md, byte-identical to PRD.md.** PRD.md 432 → PRD_FINALIZED.md 432 lines, 0.0% delta; `diff` empty (orchestrator re-verified).

`<step_7_diff>` contained exactly one item: a pure test-side variable-binding bug in `test_suite/test_08_statement_close.py:408` (`store_yt` bound to the id string, indexed as `store_yt["id"]`). The repair rebound the name to the dict; assertions untouched, no helper changed, no deletions, implementation unmodified. A binding error inside a test's setup block never reached the server, so it exposes no PRD ambiguity or silence.

Pre-edit search log: (a) subject — Content-ID bonus tier selection and final-close commission split (§3.8). (b) impl paths enumerated: `services/calc.py:148-157` (content_id_bonus_cents), `calc.py:130-144` (commission_cents PROVISIONAL/FINAL, cap+floor), `services/core.py:18,28-31` (constants), `routes/royalty.py:52,184,205-208,275` (every write/read of content_id_bonus_cents), `calc.py:60` (content_id_gross accumulation). All agree verbatim with PRD as written (tiers 200000→500bps / 50000→200bps, flat 3000 bps Content-ID commission, 2000 bps cap, 50-cent floor, tier read from pre-bonus gross with no feedback, half-up via exact Fraction). (c) no wording adjustment required.

## Step 9: Complete PRD — 2026-07-18T10:23:00.000Z

`PRD_FINALIZED.md` 432 lines / 76,631 chars → `PRD_COMPLETED.md` 432 lines / 82,011 chars (**+5,380 chars**, 18 lines touched, no lines added/removed — every change an in-paragraph insert or revision).

**Counts: 17 ambiguity-pins, 2 mismatch-revisions (19 edits).**

- §2.1 — insert — ambiguity — `Fan` pre-save still requires a present, non-empty `X-User-ID`; the value is just never compared to an entity — `middleware.py:15`
- §2.3 — insert — ambiguity — `created_at` ASC ties broken by an internal, never-exposed monotonic insertion sequence; same sequence is the final tie-break for every "created_at earliest first" rule (incl. §3.8 largest-remainder) — `response.py:105-110`, `db.py:90`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` read from the logical clock, not wall time — `db.py:82-97`
- §2.5 — insert — ambiguity — the envelope's `api_request_timestamp` is the one timestamp read from wall clock — `response.py:18-20`
- §2.8 step 3 — revise — mismatch — nonexistent identifiers report `ERR_RESOURCE_NOT_FOUND` rather than an ownership failure; body-derived ownership precedes request shape, path-derived ownership follows it — `releases.py:30,110`, `collaborators.py:32,103`, `tracks.py:113`, `splits.py:94`
- §3.1 — revise — mismatch — plan `code` casing not enforced; only 2–32 length + uniqueness — `catalogue.py:32`
- §3.2 — insert — ambiguity — activating a `PENDING` subscription against a non-`ACTIVE` artist yields `ERR_INVALID_STATE`; the artist check does not guard the `PAST_DUE` restore path — `subscriptions.py:76-81`
- §3.2 — insert — ambiguity — submit gates (and §3.3's Content-ID check) read the artist's most recently created subscription row whatever its status, `PENDING` included — looser than §3.7's pricing selection — `core.py:180-186`, `releases.py:147`, `tracks.py:16`
- §3.3 — insert — ambiguity — track amendment has no state precondition — `tracks.py:101-133`
- §3.3 — insert — ambiguity — a null `pre_save_opens_at` closes the window outright; pre-save persists no resource, answers 200 with the updated release — `releases.py:277-288`
- §3.4 — insert — ambiguity — accept recomputes `accepted_share_count` without advancing the sheet's `version`/`updated_at`, reject bumps sheet + rejecting share; re-accepting an already-accepted share is permitted and re-stamps — `splits.py:201-205,219-225`
- §3.4 — insert — ambiguity — accept against a non-`PENDING_ACCEPTANCE` sheet, and reject failing either condition, both give `ERR_INVALID_STATE` — `splits.py:198,216`
- §3.4 — insert — ambiguity — writing `locked_split_sheet_id` at lock does not advance the parent track's `version` — `splits.py:158`
- §3.6 — insert — ambiguity — the final takedown hop drives `delivery_status` to `TAKEN_DOWN` regardless, but the editorial hop, release `taken_down_at` and track deactivation fire only when the release stands at `LIVE` — `deliveries.py:227-239`
- §3.7 — insert — ambiguity — ingest answers with the updated statement, not the lines; an empty `lines` array is a valid batch that still moves `OPEN → INGESTING` and bumps `version` — `royalty.py:119-136`
- §3.8 — insert — ambiguity — payout creation order (first-encounter walk over tracks then shares, both by `created_at` + insertion sequence), all payouts of one close sharing that close instant as `created_at`; zero-cent payees still get a row — `calc.py:180,208,225-226`, `royalty.py:227-233`
- §3.8 — insert — ambiguity — each payout's effect on its collaborator refreshes `updated_at` and bumps `version`, except when no bucket moves — `calc.py:64-79`, `royalty.py:262`
- §3.8 — insert — ambiguity — close advances the artist's `version` unconditionally, even for a zero-gross statement — `royalty.py:212-214`
- §3.9 — insert — ambiguity — a below-threshold issue mutates nothing: recomputed total not persisted, `version` and `DRAFT` status unchanged — `tax_forms.py:99-106`

Both impl-generator-flagged ambiguities (§3.4 accept-vs-reject version bumps; logical-clock `created_at` + insertion-sequence tiebreak) were verified against the code and pinned.

## Pipeline complete — 2026-07-18T10:23:00.000Z

Steps 1–9 all executed. Final state: 90/90 tests passing across 8 sweep rounds; PRD.md / PRD_FINALIZED.md (0-edit) / PRD_COMPLETED.md (19 edits) all present.
