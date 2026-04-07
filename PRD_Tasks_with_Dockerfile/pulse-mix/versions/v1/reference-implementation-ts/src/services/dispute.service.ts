import db from '../db/schema';
import { v4 as uuidv4 } from 'uuid';
import {
  Dispute, DisputeRow, DisputeSeverity, DisputeTargetType,
  DisputeResolution, Effect, MixRow, AssetRow, ClearanceRow
} from '../types';
import { getStudioWithDerived, shedBudget, getStudioEffect } from './studio.service';
import { quarantineAsset, retireAsset } from './asset.service';
import { getClearanceByAsset, revokeClearance } from './clearance.service';

export function getDispute(disputeId: string): Dispute | null {
  const row = db.prepare('SELECT * FROM disputes WHERE id = ?').get(disputeId) as DisputeRow | undefined;
  if (!row) return null;
  return {
    id: row.id,
    studio_id: row.studio_id,
    target_type: row.target_type,
    target_id: row.target_id,
    severity: row.severity,
    status: row.status,
    resolution: row.resolution,
    version: row.version,
  };
}

export function createDispute(
  studioId: string,
  targetType: DisputeTargetType,
  targetId: string,
  severity: DisputeSeverity
): { dispute: Dispute; effects: Effect[] } | { error: string } {
  
  if (targetType === 'ASSET') {
    const asset = db.prepare('SELECT * FROM assets WHERE id = ? AND studio_id = ?').get(targetId, studioId) as AssetRow | undefined;
    if (!asset) return { error: 'NOT_FOUND' };
  } else {
    const mix = db.prepare('SELECT * FROM mixes WHERE id = ? AND studio_id = ?').get(targetId, studioId) as MixRow | undefined;
    if (!mix) return { error: 'NOT_FOUND' };
  }

  const id = uuidv4();
  const status = severity === 'HIGH' ? 'ESCALATED' : 'OPEN';

  db.prepare(`
    INSERT INTO disputes (id, studio_id, target_type, target_id, severity, status, version)
    VALUES (?, ?, ?, ?, ?, ?, 1)
  `).run(id, studioId, targetType, targetId, severity, status);

  const effects: Effect[] = [];

  if (targetType === 'ASSET') {
    
    const assetEffects = quarantineAsset(targetId);
    effects.push(...assetEffects);

    
    const mixEffects = handleDisputeOnAssetMixes(targetId, severity);
    effects.push(...mixEffects);
  } else {
    
    const mixEffects = handleDisputeOnMix(targetId, severity);
    effects.push(...mixEffects);
  }

  
  const shedEffects = shedBudget(studioId);
  effects.push(...shedEffects);

  
  effects.push(getStudioEffect(studioId));

  const dispute = getDispute(id)!;
  return { dispute, effects };
}

function handleDisputeOnAssetMixes(assetId: string, severity: DisputeSeverity): Effect[] {
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
    } else if (mix.status === 'PUBLISHED') {
      if (severity === 'HIGH') {
        
        db.prepare(`
          UPDATE mixes SET status = 'ARCHIVED', version = version + 1, updated_at = datetime('now')
          WHERE id = ?
        `).run(mix_id);
        effects.push({ type: 'mix', id: mix_id, status: 'ARCHIVED', version: mix.version + 1, token_cost: mix.token_cost });
      } else {
        
        db.prepare(`
          UPDATE mixes SET status = 'FROZEN', version = version + 1, updated_at = datetime('now')
          WHERE id = ?
        `).run(mix_id);
        effects.push({ type: 'mix', id: mix_id, status: 'FROZEN', version: mix.version + 1, token_cost: mix.token_cost });
      }
    }
  }

  return effects;
}

function handleDisputeOnMix(mixId: string, severity: DisputeSeverity): Effect[] {
  const effects: Effect[] = [];

  const mix = db.prepare('SELECT * FROM mixes WHERE id = ?').get(mixId) as MixRow | undefined;
  if (!mix) return effects;

  if (mix.status === 'SUBMITTED' || mix.status === 'APPROVED') {
    
    db.prepare(`
      UPDATE mixes SET status = 'DRAFT', approved_in_cycle = NULL, version = version + 1, updated_at = datetime('now')
      WHERE id = ?
    `).run(mixId);
    effects.push({ type: 'mix', id: mixId, status: 'DRAFT', version: mix.version + 1, token_cost: mix.token_cost });
  } else if (mix.status === 'PUBLISHED') {
    if (severity === 'HIGH') {
      
      db.prepare(`
        UPDATE mixes SET status = 'ARCHIVED', version = version + 1, updated_at = datetime('now')
        WHERE id = ?
      `).run(mixId);
      effects.push({ type: 'mix', id: mixId, status: 'ARCHIVED', version: mix.version + 1, token_cost: mix.token_cost });
    } else {
      
      db.prepare(`
        UPDATE mixes SET status = 'FROZEN', version = version + 1, updated_at = datetime('now')
        WHERE id = ?
      `).run(mixId);
      effects.push({ type: 'mix', id: mixId, status: 'FROZEN', version: mix.version + 1, token_cost: mix.token_cost });
    }
  }

  return effects;
}

export function resolveDispute(
  disputeId: string,
  resolution: 'UPHELD' | 'DISMISSED'
): { dispute: Dispute; effects: Effect[] } | { error: string } {
  const dispute = getDispute(disputeId);
  if (!dispute) return { error: 'NOT_FOUND' };

  if (dispute.status !== 'OPEN' && dispute.status !== 'ESCALATED') {
    return { error: 'INVALID_STATE' };
  }

  const effects: Effect[] = [];

  db.prepare(`
    UPDATE disputes SET status = 'RESOLVED', resolution = ?, version = version + 1, updated_at = datetime('now')
    WHERE id = ?
  `).run(resolution, disputeId);

  if (resolution === 'UPHELD') {
    if (dispute.target_type === 'ASSET') {
      
      const retireEffects = retireAsset(dispute.target_id);
      effects.push(...retireEffects);

      
      const clearance = getClearanceByAsset(dispute.target_id);
      if (clearance && clearance.status !== 'REVOKED') {
        db.prepare(`
          UPDATE clearances SET status = 'REVOKED', version = version + 1, updated_at = datetime('now')
          WHERE id = ?
        `).run(clearance.id);
        effects.push({ type: 'clearance', id: clearance.id, status: 'REVOKED', version: clearance.version + 1 });
      }

      
      const mixIds = db.prepare(`
        SELECT DISTINCT mix_id FROM mix_entries WHERE asset_id = ?
      `).all(dispute.target_id) as { mix_id: string }[];

      for (const { mix_id } of mixIds) {
        const mix = db.prepare('SELECT * FROM mixes WHERE id = ?').get(mix_id) as MixRow | undefined;
        if (!mix || mix.status === 'ARCHIVED') continue;

        db.prepare(`
          UPDATE mixes SET status = 'ARCHIVED', version = version + 1, updated_at = datetime('now')
          WHERE id = ?
        `).run(mix_id);
        effects.push({ type: 'mix', id: mix_id, status: 'ARCHIVED', version: mix.version + 1, token_cost: mix.token_cost });
      }
    } else {
      
      const mix = db.prepare('SELECT * FROM mixes WHERE id = ?').get(dispute.target_id) as MixRow | undefined;
      if (mix && mix.status !== 'ARCHIVED') {
        db.prepare(`
          UPDATE mixes SET status = 'ARCHIVED', version = version + 1, updated_at = datetime('now')
          WHERE id = ?
        `).run(dispute.target_id);
        effects.push({ type: 'mix', id: dispute.target_id, status: 'ARCHIVED', version: mix.version + 1, token_cost: mix.token_cost });
      }
    }
  } else if (resolution === 'DISMISSED') {
    
    if (dispute.target_type === 'ASSET') {
      const otherDisputes = db.prepare(`
        SELECT id FROM disputes
        WHERE target_type = 'ASSET' AND target_id = ? AND id != ? AND status IN ('OPEN', 'ESCALATED')
      `).all(dispute.target_id, disputeId);

      if (otherDisputes.length === 0) {
        const asset = db.prepare('SELECT * FROM assets WHERE id = ?').get(dispute.target_id) as AssetRow | undefined;
        if (asset && asset.status === 'QUARANTINED') {
          db.prepare(`
            UPDATE assets SET status = 'ACTIVE', version = version + 1, updated_at = datetime('now')
            WHERE id = ?
          `).run(dispute.target_id);
          effects.push({ type: 'asset', id: dispute.target_id, status: 'ACTIVE', version: asset.version + 1 });
        }
      }
    }
  }

  
  const shedEffects = shedBudget(dispute.studio_id);
  effects.push(...shedEffects);

  
  effects.push(getStudioEffect(dispute.studio_id));

  const updated = getDispute(disputeId)!;
  return { dispute: updated, effects };
}

export function voidDispute(disputeId: string): { dispute: Dispute; effects: Effect[] } | { error: string } {
  const dispute = getDispute(disputeId);
  if (!dispute) return { error: 'NOT_FOUND' };

  if (dispute.status !== 'OPEN' && dispute.status !== 'ESCALATED') {
    return { error: 'INVALID_STATE' };
  }

  const effects: Effect[] = [];

  db.prepare(`
    UPDATE disputes SET status = 'VOID', resolution = 'VOID', version = version + 1, updated_at = datetime('now')
    WHERE id = ?
  `).run(disputeId);

  
  if (dispute.target_type === 'ASSET') {
    const otherDisputes = db.prepare(`
      SELECT id FROM disputes
      WHERE target_type = 'ASSET' AND target_id = ? AND id != ? AND status IN ('OPEN', 'ESCALATED')
    `).all(dispute.target_id, disputeId);

    if (otherDisputes.length === 0) {
      const asset = db.prepare('SELECT * FROM assets WHERE id = ?').get(dispute.target_id) as AssetRow | undefined;
      if (asset && asset.status === 'QUARANTINED') {
        db.prepare(`
          UPDATE assets SET status = 'ACTIVE', version = version + 1, updated_at = datetime('now')
          WHERE id = ?
        `).run(dispute.target_id);
        effects.push({ type: 'asset', id: dispute.target_id, status: 'ACTIVE', version: asset.version + 1 });
      }
    }
  }

  
  const shedEffects = shedBudget(dispute.studio_id);
  effects.push(...shedEffects);

  
  effects.push(getStudioEffect(dispute.studio_id));

  const updated = getDispute(disputeId)!;
  return { dispute: updated, effects };
}
