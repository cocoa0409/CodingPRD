import db from '../db/schema';
import { v4 as uuidv4 } from 'uuid';
import { Asset, AssetRow, AssetStatus, Effect, ClearanceRow, DisputeRow, MixRow } from '../types';
import { calculatePosture, getStudioWithDerived } from './studio.service';

export function getAsset(assetId: string): Asset | null {
  const row = db.prepare('SELECT * FROM assets WHERE id = ?').get(assetId) as AssetRow | undefined;
  if (!row) return null;
  return {
    id: row.id,
    studio_id: row.studio_id,
    title: row.title,
    duration_sec: row.duration_sec,
    status: row.status,
    version: row.version,
  };
}

export function createAsset(studioId: string, title: string, durationSec: number): Asset {
  const id = uuidv4();
  db.prepare(`
    INSERT INTO assets (id, studio_id, title, duration_sec, status, version)
    VALUES (?, ?, ?, ?, 'DRAFT', 1)
  `).run(id, studioId, title, durationSec);

  return getAsset(id)!;
}

export function updateAsset(assetId: string, updates: { title?: string; duration_sec?: number }): Asset {
  const setClauses: string[] = [];
  const params: (string | number)[] = [];

  if (updates.title !== undefined) {
    setClauses.push('title = ?');
    params.push(updates.title);
  }
  if (updates.duration_sec !== undefined) {
    setClauses.push('duration_sec = ?');
    params.push(updates.duration_sec);
  }

  if (setClauses.length > 0) {
    setClauses.push('version = version + 1');
    setClauses.push("updated_at = datetime('now')");
    params.push(assetId);

    db.prepare(`
      UPDATE assets SET ${setClauses.join(', ')} WHERE id = ?
    `).run(...params);
  }

  return getAsset(assetId)!;
}

export function hasOpenDispute(targetType: 'ASSET' | 'MIX', targetId: string): boolean {
  const dispute = db.prepare(`
    SELECT id FROM disputes
    WHERE target_type = ? AND target_id = ? AND status IN ('OPEN', 'ESCALATED')
    LIMIT 1
  `).get(targetType, targetId);
  return !!dispute;
}

export function activateAsset(assetId: string): { asset: Asset; effects: Effect[] } | { error: string } {
  const asset = getAsset(assetId);
  if (!asset) return { error: 'NOT_FOUND' };

  const studio = getStudioWithDerived(asset.studio_id);
  if (!studio) return { error: 'NOT_FOUND' };

  if (asset.status !== 'DRAFT') {
    return { error: 'INVALID_STATE' };
  }

  if (studio.posture === 'HALT') {
    return { error: 'POSTURE_BLOCKED' };
  }

  
  const clearance = db.prepare(`
    SELECT * FROM clearances WHERE asset_id = ?
  `).get(assetId) as ClearanceRow | undefined;

  if (!clearance || clearance.status !== 'GRANTED') {
    return { error: 'CLEARANCE_REQUIRED' };
  }

  
  if (hasOpenDispute('ASSET', assetId)) {
    return { error: 'DISPUTE_BLOCKING' };
  }

  db.prepare(`
    UPDATE assets SET status = 'ACTIVE', version = version + 1, updated_at = datetime('now')
    WHERE id = ?
  `).run(assetId);

  const updatedAsset = getAsset(assetId)!;
  return { asset: updatedAsset, effects: [] };
}

export function quarantineAsset(assetId: string): Effect[] {
  const effects: Effect[] = [];
  const asset = getAsset(assetId);
  if (!asset || asset.status === 'RETIRED') return effects;

  if (asset.status !== 'QUARANTINED') {
    db.prepare(`
      UPDATE assets SET status = 'QUARANTINED', version = version + 1, updated_at = datetime('now')
      WHERE id = ?
    `).run(assetId);
    const updated = getAsset(assetId)!;
    effects.push({ type: 'asset', id: assetId, status: 'QUARANTINED', version: updated.version });
  }

  
  const clearance = db.prepare(`
    SELECT * FROM clearances WHERE asset_id = ? AND status = 'GRANTED'
  `).get(assetId) as ClearanceRow | undefined;

  if (clearance) {
    db.prepare(`
      UPDATE clearances SET status = 'SUSPENDED', version = version + 1, updated_at = datetime('now')
      WHERE id = ?
    `).run(clearance.id);
    effects.push({ type: 'clearance', id: clearance.id, status: 'SUSPENDED', version: clearance.version + 1 });
  }

  return effects;
}

export function retireAsset(assetId: string): Effect[] {
  const effects: Effect[] = [];
  const asset = getAsset(assetId);
  if (!asset || asset.status === 'RETIRED') return effects;

  db.prepare(`
    UPDATE assets SET status = 'RETIRED', version = version + 1, updated_at = datetime('now')
    WHERE id = ?
  `).run(assetId);
  const updated = getAsset(assetId)!;
  effects.push({ type: 'asset', id: assetId, status: 'RETIRED', version: updated.version });

  return effects;
}

export function legalDurationCorrection(assetId: string, newDuration: number): { asset: Asset; effects: Effect[] } | { error: string } {
  const asset = getAsset(assetId);
  if (!asset) return { error: 'NOT_FOUND' };

  if (asset.status !== 'ACTIVE' && asset.status !== 'QUARANTINED') {
    return { error: 'INVALID_STATE' };
  }

  const effects: Effect[] = [];

  
  db.prepare(`
    UPDATE assets SET duration_sec = ?, status = 'QUARANTINED', version = version + 1, updated_at = datetime('now')
    WHERE id = ?
  `).run(newDuration, assetId);

  
  const clearance = db.prepare(`
    SELECT * FROM clearances WHERE asset_id = ? AND status = 'GRANTED'
  `).get(assetId) as ClearanceRow | undefined;

  if (clearance) {
    db.prepare(`
      UPDATE clearances SET status = 'SUSPENDED', version = version + 1, updated_at = datetime('now')
      WHERE id = ?
    `).run(clearance.id);
    effects.push({ type: 'clearance', id: clearance.id, status: 'SUSPENDED', version: clearance.version + 1 });
  }

  
  const mixEffects = handleAssetStatusChangeForMixes(assetId, asset.studio_id);
  effects.push(...mixEffects);

  const updatedAsset = getAsset(assetId)!;
  effects.unshift({ type: 'asset', id: assetId, status: 'QUARANTINED', version: updatedAsset.version });

  return { asset: updatedAsset, effects };
}

export function handleAssetStatusChangeForMixes(assetId: string, studioId: string): Effect[] {
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
    }
    
    else if (mix.status === 'PUBLISHED') {
      db.prepare(`
        UPDATE mixes SET status = 'FROZEN', version = version + 1, updated_at = datetime('now')
        WHERE id = ?
      `).run(mix_id);
      effects.push({ type: 'mix', id: mix_id, status: 'FROZEN', version: mix.version + 1, token_cost: mix.token_cost });
    }
  }

  return effects;
}

export function recalculateMixTokenCosts(assetId: string): Effect[] {
  const effects: Effect[] = [];

  const mixIds = db.prepare(`
    SELECT DISTINCT mix_id FROM mix_entries WHERE asset_id = ?
  `).all(assetId) as { mix_id: string }[];

  for (const { mix_id } of mixIds) {
    const { calculateMixTokenCost, getMix } = require('./mix.service');
    const newCost = calculateMixTokenCost(mix_id);
    const mix = db.prepare('SELECT * FROM mixes WHERE id = ?').get(mix_id) as MixRow;

    if (mix.token_cost !== newCost) {
      db.prepare(`
        UPDATE mixes SET token_cost = ?, version = version + 1, updated_at = datetime('now')
        WHERE id = ?
      `).run(newCost, mix_id);
      effects.push({ type: 'mix', id: mix_id, version: mix.version + 1, token_cost: newCost, status: mix.status });
    }
  }

  return effects;
}
