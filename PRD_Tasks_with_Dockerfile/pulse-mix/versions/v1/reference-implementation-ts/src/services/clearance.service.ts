import db from '../db/schema';
import { v4 as uuidv4 } from 'uuid';
import { Clearance, ClearanceRow, ClearancePolicy, Effect, MixRow, AssetRow } from '../types';
import { getStudioWithDerived, shedBudget, getStudioEffect } from './studio.service';
import { retireAsset } from './asset.service';

export function getClearance(clearanceId: string): Clearance | null {
  const row = db.prepare('SELECT * FROM clearances WHERE id = ?').get(clearanceId) as ClearanceRow | undefined;
  if (!row) return null;
  return {
    id: row.id,
    studio_id: row.studio_id,
    asset_id: row.asset_id,
    policy: row.policy,
    status: row.status,
    last_granted_in_cycle: row.last_granted_in_cycle,
    version: row.version,
  };
}

export function getClearanceByAsset(assetId: string): Clearance | null {
  const row = db.prepare('SELECT * FROM clearances WHERE asset_id = ?').get(assetId) as ClearanceRow | undefined;
  if (!row) return null;
  return {
    id: row.id,
    studio_id: row.studio_id,
    asset_id: row.asset_id,
    policy: row.policy,
    status: row.status,
    last_granted_in_cycle: row.last_granted_in_cycle,
    version: row.version,
  };
}

export function createClearance(studioId: string, assetId: string, policy: ClearancePolicy): Clearance | { error: string } {
  
  const existing = db.prepare('SELECT id FROM clearances WHERE asset_id = ?').get(assetId);
  if (existing) {
    return { error: 'CLEARANCE_ALREADY_EXISTS' };
  }

  
  const asset = db.prepare('SELECT * FROM assets WHERE id = ? AND studio_id = ?').get(assetId, studioId) as AssetRow | undefined;
  if (!asset) {
    return { error: 'NOT_FOUND' };
  }

  const id = uuidv4();
  db.prepare(`
    INSERT INTO clearances (id, studio_id, asset_id, policy, status, version)
    VALUES (?, ?, ?, ?, 'PENDING', 1)
  `).run(id, studioId, assetId, policy);

  return getClearance(id)!;
}

export function grantClearance(clearanceId: string, studioId: string): { clearance: Clearance; effects: Effect[] } | { error: string } {
  const clearance = getClearance(clearanceId);
  if (!clearance || clearance.studio_id !== studioId) {
    return { error: 'NOT_FOUND' };
  }

  const studio = getStudioWithDerived(studioId);
  if (!studio) return { error: 'NOT_FOUND' };

  if (studio.posture === 'HALT') {
    return { error: 'POSTURE_BLOCKED' };
  }

  if (clearance.status === 'REVOKED') {
    return { error: 'INVALID_STATE' };
  }

  db.prepare(`
    UPDATE clearances
    SET status = 'GRANTED', last_granted_in_cycle = ?, version = version + 1, updated_at = datetime('now')
    WHERE id = ?
  `).run(studio.cycle_index, clearanceId);

  const updated = getClearance(clearanceId)!;
  return { clearance: updated, effects: [] };
}

export function suspendClearance(clearanceId: string, studioId: string): { clearance: Clearance; effects: Effect[] } | { error: string } {
  const clearance = getClearance(clearanceId);
  if (!clearance || clearance.studio_id !== studioId) {
    return { error: 'NOT_FOUND' };
  }

  if (clearance.status === 'REVOKED') {
    return { error: 'INVALID_STATE' };
  }

  const effects: Effect[] = [];

  db.prepare(`
    UPDATE clearances SET status = 'SUSPENDED', version = version + 1, updated_at = datetime('now')
    WHERE id = ?
  `).run(clearanceId);

  
  const mixEffects = handleClearanceChange(clearance.asset_id, 'SUSPENDED');
  effects.push(...mixEffects);

  
  const shedEffects = shedBudget(studioId);
  effects.push(...shedEffects);

  if (shedEffects.length > 0 || mixEffects.length > 0) {
    effects.push(getStudioEffect(studioId));
  }

  const updated = getClearance(clearanceId)!;
  return { clearance: updated, effects };
}

export function revokeClearance(clearanceId: string, studioId: string, fromUpheldDispute: boolean = false): { clearance: Clearance; effects: Effect[] } | { error: string } {
  const clearance = getClearance(clearanceId);
  if (!clearance || clearance.studio_id !== studioId) {
    return { error: 'NOT_FOUND' };
  }

  if (clearance.status === 'REVOKED') {
    return { error: 'INVALID_STATE' };
  }

  const effects: Effect[] = [];

  db.prepare(`
    UPDATE clearances SET status = 'REVOKED', version = version + 1, updated_at = datetime('now')
    WHERE id = ?
  `).run(clearanceId);

  
  const mixEffects = handleClearanceChange(clearance.asset_id, 'REVOKED');
  effects.push(...mixEffects);

  
  if (fromUpheldDispute) {
    const retireEffects = retireAsset(clearance.asset_id);
    effects.push(...retireEffects);
  }

  
  const shedEffects = shedBudget(studioId);
  effects.push(...shedEffects);

  if (shedEffects.length > 0 || mixEffects.length > 0) {
    effects.push(getStudioEffect(studioId));
  }

  const updated = getClearance(clearanceId)!;
  return { clearance: updated, effects };
}

function handleClearanceChange(assetId: string, newStatus: 'SUSPENDED' | 'REVOKED'): Effect[] {
  const effects: Effect[] = [];

  
  const mixIds = db.prepare(`
    SELECT DISTINCT mix_id FROM mix_entries WHERE asset_id = ?
  `).all(assetId) as { mix_id: string }[];

  for (const { mix_id } of mixIds) {
    const mix = db.prepare('SELECT * FROM mixes WHERE id = ?').get(mix_id) as MixRow | undefined;
    if (!mix) continue;

    if (mix.status === 'SUBMITTED' || mix.status === 'APPROVED') {
      
      db.prepare(`
        UPDATE mixes SET status = 'DRAFT', approved_in_cycle = NULL, version = version + 1, updated_at = datetime('now')
        WHERE id = ?
      `).run(mix_id);
      effects.push({ type: 'mix', id: mix_id, status: 'DRAFT', version: mix.version + 1, token_cost: mix.token_cost });
    } else if (mix.status === 'PUBLISHED' || mix.status === 'FROZEN') {
      if (newStatus === 'SUSPENDED') {
        
        if (mix.status !== 'FROZEN') {
          db.prepare(`
            UPDATE mixes SET status = 'FROZEN', version = version + 1, updated_at = datetime('now')
            WHERE id = ?
          `).run(mix_id);
          effects.push({ type: 'mix', id: mix_id, status: 'FROZEN', version: mix.version + 1, token_cost: mix.token_cost });
        }
      } else {
        
        db.prepare(`
          UPDATE mixes SET status = 'ARCHIVED', version = version + 1, updated_at = datetime('now')
          WHERE id = ?
        `).run(mix_id);
        effects.push({ type: 'mix', id: mix_id, status: 'ARCHIVED', version: mix.version + 1, token_cost: mix.token_cost });
      }
    }
  }

  return effects;
}
